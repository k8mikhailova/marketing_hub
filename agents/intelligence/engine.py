"""Intelligence Agent: deterministic preview implementation.

No LLM call exists yet. Everything here is arithmetic and rule-based
interpretation over evidence that core/ has already computed. This is
explicitly the "preview" implementation described in the README: it
returns the same Finding schema a future live agent would return, produced
by fixed rules instead of a model call. Every number in a Finding's prose
traces to a specific core/ function's output, attached as Evidence; nothing
here invents a metric or performs arithmetic that isn't already in core/.

Boundaries (see agents/intelligence/agent.md for the full spec):
- Does not generate ad creative, decide experiments, or approve learnings.
- Does not act as the Performance Agent or the Creative Strategist.
- Never claims observational performance data proves causation: every
  performance-based finding is phrased as an association or a hypothesis
  worth testing, not a settled result.
- Confidence is capped at "medium" for any forward-looking hypothesis
  (Emerging Opportunity, Messaging Gap), regardless of how strong the
  supporting numbers are, because the recommendation itself is untested.
  "High" is reserved for findings that describe an already-observed
  pattern with volume comfortably above the noise floor.
"""
from dataclasses import dataclass, field

import pandas as pd

from core.analytics import (
    PERFORMANCE_MIN_PURCHASES,
    PERFORMANCE_MIN_RELATIVE_GAP,
    PERFORMANCE_MIN_SPEND,
    attribute_style_leaders,
    theme_associated_products,
    theme_movement,
)
from core.creative_coverage import CUSTOMER_THEME_TO_CREATIVE_KEYWORDS, creative_coverage
from core.data import load_creative_catalog, load_customer_signals, load_performance_with_creatives

GENERATED_BY_PREVIEW = "preview"  # a future live agent would set generated_by="agent"

# Finding types that describe something worth exploring, not something
# already settled (Performance Pattern) or an explicit non-action
# (Saturated Theme). Only these reasonably become a creative experiment.
# Defined here, once, so Marketing Intelligence and the Creative Strategist
# can't silently disagree about which findings are experiment-worthy.
EXPERIMENT_WORTHY_TYPES = {"Emerging Opportunity", "Messaging Gap"}

# Noise/volume floors. Same philosophy as core/insights.py: a finding never
# rests on a handful of rows, and thresholds are named constants, not magic
# numbers buried in a condition. PERFORMANCE_MIN_SPEND/PURCHASES/RELATIVE_GAP
# now live in core/analytics.py (imported above) since they're deterministic
# facts about how much volume a comparison needs, not agent-specific
# interpretation; re-exported here so existing importers of this module
# (app_pages/creative_lab.py, app_pages/intelligence.py) don't need to change.
EMERGING_MIN_CHANGE = 10  # a theme must gain at least this many signals to count as "emerging"
EMERGING_MIN_CURRENT_COUNT = 15  # and have at least this many signals in the current period
LOW_COVERAGE_MAX_HOOK_RATIO = 0.15  # "rarely leads" ceiling for an opportunity-worthy gap
GAP_MIN_SIGNAL_SHARE = 0.10  # a theme must be at least this big a share of signals to name as a gap
SATURATED_MIN_HOOK_RATIO = 0.40  # "already well covered" floor; nothing in the demo data clears this today


@dataclass
class Evidence:
    """One traceable fact behind a finding. Always the output of a core/
    function; the agent layer never asserts a number that isn't here."""

    label: str
    detail: str
    source: str  # which dataset(s) and core/ function this traces to
    table: pd.DataFrame | None = None


@dataclass
class Finding:
    """The Intelligence Agent's structured output. A future live agent
    (an LLM call) would return this same shape; generated_by distinguishes
    which one produced a given instance."""

    finding_id: str
    type: str
    title: str
    summary: str
    why_it_matters: str
    confidence: str  # "low" | "medium" | "high"
    evidence: list[Evidence] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    recommended_next_step: str = ""
    generated_by: str = GENERATED_BY_PREVIEW


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace("&", "and").replace("/", "_").replace("__", "_")


def _humanize(value: str) -> str:
    """Display formatting only: "benefit_plus_proof" -> "benefit plus proof"."""
    return value.replace("_", " ")


def _default_window(signals: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The latest 30 days of available signal history, the same default
    every page in this app uses, so a finding's numbers match what a
    marketer sees on Overview or Customer Signals for the same period."""
    end = signals["date"].max()
    start = end - pd.Timedelta(days=29)
    return start, end


def _theme_evidence_base(client_id: str) -> dict:
    """Shared per-theme evidence: movement, associated products (limited to
    products that actually exist in the creative catalog), and creative
    coverage. Computed once and reused by every detector below, so two
    detectors can never silently disagree about the same theme's numbers.
    """
    signals = load_customer_signals(client_id)
    catalog = load_creative_catalog(client_id)
    if signals.empty or catalog.empty:
        return {}

    start, end = _default_window(signals)
    movement_table, movement_available = theme_movement(signals, start, end)
    catalog_products = set(catalog["product_name"].unique())

    themes = {}
    for _, row in movement_table.iterrows():
        theme = row["demo_theme_label"]
        if theme not in CUSTOMER_THEME_TO_CREATIVE_KEYWORDS:
            continue
        assoc = theme_associated_products(signals, theme)
        assoc_products = [p for p in assoc["product_context"] if p in catalog_products]
        excluded_products = [p for p in assoc["product_context"] if p not in catalog_products]
        coverage = creative_coverage(catalog, theme, products=assoc_products) if assoc_products else None
        themes[theme] = {
            "signal_count": int(row["signal_count"]),
            "share_of_total": float(row["share_of_total"]),
            "previous_count": int(row["previous_count"]) if movement_available else None,
            "change": int(row["change"]) if movement_available else None,
            "movement_available": movement_available,
            "associated_products": assoc_products,
            "excluded_products": excluded_products,
            "coverage": coverage,
        }

    return {"themes": themes, "window": (start, end)}


def message_style_leaders(joined: pd.DataFrame, products: list[str] | None = None) -> list[dict]:
    """Every (product, funnel_stage) cell where one message_style clearly
    leads (higher ROAS AND higher CTR than every other qualifying style in
    that same cell), ranked by the size of the ROAS gap, largest first.

    Never compares styles across different funnel stages or products:
    those have different economics by design (a BOF retargeting offer and
    a TOF awareness ad aren't a fair comparison). This is the single
    definition of "which style leads" used by _detect_performance_patterns,
    _supporting_message_style_evidence, and the Marketing Intelligence
    page's Creative Performance Patterns table, so all three can't disagree
    with each other. Public (no leading underscore) because the page
    imports it directly to highlight the same qualifying rows it computes
    here, rather than re-deriving the criteria in the UI layer.

    A thin wrapper over core.analytics.attribute_style_leaders (the same
    comparison rule, generalized so core/visual_performance.py can reuse it
    for a visual attribute without duplicating this logic); only the key
    names differ (leader_style/runner_up_style here vs leader_value/
    runner_up_value there), kept for every existing caller of this function.
    """
    leaders = attribute_style_leaders(
        joined,
        "message_style",
        products=products,
        min_spend=PERFORMANCE_MIN_SPEND,
        min_purchases=PERFORMANCE_MIN_PURCHASES,
        min_relative_gap=PERFORMANCE_MIN_RELATIVE_GAP,
    )
    for leader in leaders:
        leader["leader_style"] = leader.pop("leader_value")
        leader["runner_up_style"] = leader.pop("runner_up_value")
    return leaders


def _supporting_message_style_evidence(joined: pd.DataFrame, products: list[str]):
    """The strongest message-style pattern (see message_style_leaders)
    within `products`, as evidence to fold into an Emerging Opportunity
    finding. Returns (summary_dict, Evidence) or (None, None) if no clean
    pattern exists; never forces a comparison the data doesn't support.
    """
    if not products:
        return None, None
    leaders = message_style_leaders(joined, products=products)
    if not leaders:
        return None, None

    best = leaders[0]
    evidence = Evidence(
        label="Messaging performance",
        detail=(
            f"Within {best['product_name']} {best['funnel_stage']}, {_humanize(best['leader_style'])} messaging "
            f"returns {best['leader_roas']:.2f}x ROAS and {best['leader_ctr']:.2%} CTR, versus "
            f"{best['rest_best_roas']:.2f}x ROAS for the next-best qualifying style in that same context."
        ),
        source="meta_ads.csv + creative_catalog.csv (core.analytics.aggregate_performance)",
        table=best["cell_table"],
    )
    summary = {
        "candidate_style": best["leader_style"],
        "context": f"{best['product_name']} {best['funnel_stage']}",
        "product_name": best["product_name"],
        "funnel_stage": best["funnel_stage"],
    }
    return summary, evidence


def _detect_emerging_opportunities(joined: pd.DataFrame, ctx: dict) -> tuple[list[Finding], set]:
    """A theme growing in customer conversation, with little of its
    associated products' creative leading with it. When a supporting
    message-style pattern also exists in that same product context, it's
    folded in as additional evidence, not a separate finding.

    Also returns the set of (product, funnel_stage) cells actually cited as
    supporting evidence, so generate_findings can keep _detect_performance_
    patterns from raising the exact same evidence again as if it were an
    independent discovery. Only the specific cited cell is excluded, not
    every product the theme merely touches, so a genuinely different
    pattern elsewhere in the same product can still surface.
    """
    start, end = ctx["window"]
    period_days = (end - start).days + 1
    findings = []
    cited_cells = set()

    for theme, info in ctx["themes"].items():
        if not info["movement_available"] or info["change"] is None:
            continue
        if info["change"] < EMERGING_MIN_CHANGE or info["signal_count"] < EMERGING_MIN_CURRENT_COUNT:
            continue
        coverage = info["coverage"]
        if coverage is None or coverage["primary_hook_ratio"] > LOW_COVERAGE_MAX_HOOK_RATIO:
            continue

        products = info["associated_products"]
        products_label = ", ".join(products)
        perf_summary, perf_evidence = _supporting_message_style_evidence(joined, products)

        evidence = [
            Evidence(
                label="Customer signal volume",
                detail=(
                    f'"{theme}" had {info["signal_count"]} signals in the latest {period_days} days, '
                    f'versus {info["previous_count"]} in the prior {period_days} days ({info["change"]:+d}).'
                ),
                source="customer_signals.csv (core.analytics.theme_movement)",
            ),
            Evidence(
                label="Creative coverage",
                detail=(
                    f'Of {coverage["relevant_creatives"]} creatives for {products_label}, '
                    f'{coverage["primary_hook_count"]} lead with "{theme}" and {coverage["mentioned_count"]} '
                    f"mention it in supporting copy."
                ),
                source="creative_catalog.csv (core.creative_coverage.creative_coverage)",
            ),
        ]
        if perf_evidence:
            evidence.append(perf_evidence)
            cited_cells.add((perf_summary["product_name"], perf_summary["funnel_stage"]))

        why_it_matters = (
            f'Customer conversation about "{theme}" is growing, but creative for {products_label} rarely '
            f"leads with it, so this may be an untapped angle worth testing."
        )
        recommendation = f'Explore a "{theme}"-led concept for {products[0]}'
        if perf_summary:
            why_it_matters += (
                f' Within {perf_summary["context"]}, {_humanize(perf_summary["candidate_style"])} messaging '
                f"already shows a stronger balance of attention and conversion efficiency than other "
                f"qualifying styles in that same context."
            )
            recommendation += f', informed by {_humanize(perf_summary["candidate_style"])} messaging'
        recommendation += ", while retaining what already works, subject to human review."

        findings.append(
            Finding(
                finding_id=f"emerging_opportunity::{_slug(theme)}",
                type="Emerging Opportunity",
                title=f"{theme} is growing faster than our creative coverage",
                summary=(
                    f'"{theme}" mentions rose from {info["previous_count"]} to {info["signal_count"]} in the '
                    f"last {period_days} days, but only {coverage['primary_hook_count']} of "
                    f"{coverage['relevant_creatives']} relevant creatives lead with it."
                ),
                why_it_matters=why_it_matters,
                confidence="medium",
                evidence=evidence,
                products=products,
                themes=[theme],
                recommended_next_step=recommendation,
            )
        )

    return findings, cited_cells


def _detect_messaging_gaps(ctx: dict, exclude_themes: set) -> list[Finding]:
    """A theme with meaningful signal share and little creative coverage,
    regardless of trend direction. Distinct from Emerging Opportunity,
    which requires growth; this catches a steady or declining theme that's
    still a sizable, under-addressed share of the conversation.
    """
    findings = []
    for theme, info in ctx["themes"].items():
        if theme in exclude_themes:
            continue
        if info["share_of_total"] < GAP_MIN_SIGNAL_SHARE:
            continue
        coverage = info["coverage"]
        if coverage is None or coverage["primary_hook_ratio"] > LOW_COVERAGE_MAX_HOOK_RATIO:
            continue

        products = info["associated_products"]
        products_label = ", ".join(products)

        findings.append(
            Finding(
                finding_id=f"messaging_gap::{_slug(theme)}",
                type="Messaging Gap",
                title=f"{theme} is a common topic with little dedicated messaging",
                summary=(
                    f'"{theme}" makes up {info["share_of_total"]:.0%} of customer signals, but only '
                    f"{coverage['primary_hook_count']} of {coverage['relevant_creatives']} relevant creatives "
                    f"lead with it."
                ),
                why_it_matters=(
                    f'Customers bring up "{theme}" often, but current {products_label} creative rarely puts '
                    f"it front and center, which may be a missed way to speak to them."
                ),
                confidence="low",
                evidence=[
                    Evidence(
                        label="Customer signal volume",
                        detail=(
                            f'"{theme}" accounts for {info["signal_count"]} of the period\'s signals '
                            f'({info["share_of_total"]:.0%}).'
                        ),
                        source="customer_signals.csv (core.analytics.theme_movement)",
                    ),
                    Evidence(
                        label="Creative coverage",
                        detail=(
                            f'Of {coverage["relevant_creatives"]} creatives for {products_label}, '
                            f'{coverage["primary_hook_count"]} lead with "{theme}" and '
                            f'{coverage["mentioned_count"]} mention it in supporting copy.'
                        ),
                        source="creative_catalog.csv (core.creative_coverage.creative_coverage)",
                    ),
                ],
                products=products,
                themes=[theme],
                recommended_next_step=f'Consider a "{theme}"-led concept for {products[0]}, subject to human review.',
            )
        )
    return findings


def _detect_saturated_themes(ctx: dict) -> list[Finding]:
    """A theme that's a meaningful share of conversation and already
    well represented in creative. Explicitly informational: the point is
    to say this is probably NOT an untapped opportunity, not to recommend
    an action.
    """
    findings = []
    for theme, info in ctx["themes"].items():
        coverage = info["coverage"]
        if coverage is None or info["share_of_total"] < GAP_MIN_SIGNAL_SHARE:
            continue
        if coverage["primary_hook_ratio"] < SATURATED_MIN_HOOK_RATIO:
            continue

        products_label = ", ".join(info["associated_products"])
        findings.append(
            Finding(
                finding_id=f"saturated_theme::{_slug(theme)}",
                type="Saturated Theme",
                title=f"{theme} is already well covered by current creative",
                summary=(
                    f'{coverage["primary_hook_count"]} of {coverage["relevant_creatives"]} relevant creatives '
                    f'already lead with "{theme}".'
                ),
                why_it_matters=(
                    f'"{theme}" is well represented in current creative, so it likely is not an untapped '
                    f"angle worth prioritizing next."
                ),
                confidence="medium",
                evidence=[
                    Evidence(
                        label="Creative coverage",
                        detail=(
                            f'{coverage["primary_hook_count"]} of {coverage["relevant_creatives"]} creatives for '
                            f'{products_label} lead with "{theme}".'
                        ),
                        source="creative_catalog.csv (core.creative_coverage.creative_coverage)",
                    ),
                ],
                products=info["associated_products"],
                themes=[theme],
                recommended_next_step=f'No creative action needed for "{theme}" at this time.',
            )
        )
    return findings


def _detect_performance_patterns(joined: pd.DataFrame, exclude_cells: set) -> list[Finding]:
    """A message style clearly leading (both ROAS and CTR) within one
    product and funnel stage, on volume comfortably above the noise floor
    (see message_style_leaders). Independent of any customer theme; skips
    the exact (product, funnel_stage) cells already cited as supporting
    evidence in an Emerging Opportunity finding, so the same evidence isn't
    raised twice under two different finding types. A different funnel
    stage or product the theme didn't cite can still surface here.
    """
    findings = []
    for leader in message_style_leaders(joined):
        product, stage = leader["product_name"], leader["funnel_stage"]
        if (product, stage) in exclude_cells:
            continue

        style_label = _humanize(leader["leader_style"])
        runner_up_label = _humanize(leader["runner_up_style"])
        detail = "; ".join(
            f"{_humanize(r['message_style'])} {r['roas']:.2f}x ROAS, {r['ctr']:.2%} CTR, ${r['spend']:,.0f} spend"
            for _, r in leader["cell_table"].iterrows()
        )

        findings.append(
            Finding(
                finding_id=f"performance_pattern::{_slug(product)}::{_slug(stage)}",
                type="Performance Pattern",
                title=f"{style_label.capitalize()} is outperforming {runner_up_label} messaging for {product}",
                summary=(
                    f"Within {product} {stage}, {style_label} messaging returns "
                    f"{leader['leader_roas']:.2f}x ROAS and {leader['leader_ctr']:.2%} CTR, ahead of the "
                    f"next-best qualifying style at {leader['rest_best_roas']:.2f}x ROAS."
                ),
                why_it_matters=(
                    f"{style_label.capitalize()} messaging already leads on both attention and efficiency in "
                    f"this context, on ${leader['leader_spend']:,.0f} of spend and "
                    f"{int(leader['leader_purchases'])} purchases, enough volume to trust the comparison, "
                    f"though it may not hold in a different product or funnel stage."
                ),
                confidence="high" if leader["leader_spend"] >= PERFORMANCE_MIN_SPEND * 2 else "medium",
                evidence=[
                    Evidence(
                        label="Messaging performance",
                        detail=f"{product} {stage}: {detail}",
                        source="meta_ads.csv + creative_catalog.csv (core.analytics.aggregate_performance)",
                        table=leader["cell_table"],
                    )
                ],
                products=[product],
                themes=[],
                recommended_next_step=(
                    f"Consider allocating incremental {product} {stage} spend toward {style_label} messaging, "
                    f"subject to human review."
                ),
            )
        )
    return findings


def generate_findings(client_id: str, max_findings: int = 3) -> list[Finding]:
    """Run every detector and return the top `max_findings` candidates.

    This is the Intelligence Agent's deterministic preview entry point.
    Ranked by confidence, then by how much evidence backs the finding, so
    the most corroborated finding leads. Returns fewer than max_findings
    (including zero) when the data doesn't support that many; never pads
    the list with a weak or fabricated finding to hit a target count.
    """
    ctx = _theme_evidence_base(client_id)
    if not ctx:
        return []

    joined = load_performance_with_creatives(client_id)

    emerging, cited_cells = _detect_emerging_opportunities(joined, ctx)
    emerging_themes = {f.themes[0] for f in emerging}

    gaps = _detect_messaging_gaps(ctx, exclude_themes=emerging_themes)
    saturated = _detect_saturated_themes(ctx)
    patterns = _detect_performance_patterns(joined, exclude_cells=cited_cells)

    all_findings = emerging + gaps + saturated + patterns
    confidence_rank = {"high": 2, "medium": 1, "low": 0}
    all_findings.sort(key=lambda f: (confidence_rank[f.confidence], len(f.evidence)), reverse=True)

    # Prefer a diverse brief over a repetitive one: skip a candidate whose
    # (type, products) combination is already represented, so two similar
    # patterns about the same product don't crowd out a different story.
    # Never changes which findings exist, only which ones make the top N.
    selected = []
    seen = set()
    for finding in all_findings:
        key = (finding.type, tuple(sorted(finding.products)))
        if key in seen:
            continue
        seen.add(key)
        selected.append(finding)
        if len(selected) >= max_findings:
            break
    return selected
