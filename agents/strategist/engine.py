"""Creative Strategist: deterministic preview implementation.

Turns an experiment-worthy Marketing Intelligence Finding into a structured,
human-reviewable ExperimentProposal. Exactly like
agents/intelligence/engine.py, this is the "preview" implementation
described in the README: no LLM call exists yet, only arithmetic and
rule-based interpretation over evidence core/ and the Intelligence Agent
have already produced.

Boundaries (see agents/strategist/agent.md for the full spec):
- Does not discover customer signals or calculate performance. It consumes
  a Finding (agents/intelligence/engine.py) and traces every factual claim
  in a proposal back to that Finding's evidence, creative_catalog.csv, or
  meta_ads.csv. It never invents a number.
- Does not choose a control by picking whatever ad has the highest ROAS
  anywhere: control selection (select_control_creative) is scoped to the
  same product and funnel stage the experiment is actually about, because
  a control is a same-context baseline, not a leaderboard winner.
- Never claims a proposed direction will improve performance. Every
  hypothesis is phrased as something to test ("may", "expected", "test
  whether"), not a predicted outcome.
- Produces a proposal only. Approval, editing, and rejection are a human's
  decision in Creative Lab (app_pages/creative_lab.py); this module has no
  notion of "approved" and never writes to approved_learnings.json.
"""
from dataclasses import dataclass, field

import pandas as pd

from agents.intelligence.engine import (
    EXPERIMENT_WORTHY_TYPES,
    GENERATED_BY_PREVIEW,
    PERFORMANCE_MIN_PURCHASES,
    PERFORMANCE_MIN_SPEND,
    Evidence,
    Finding,
    generate_findings,
    message_style_leaders,
)
from core.analytics import aggregate_performance
from core.data import load_creative_catalog, load_customer_signals, load_performance_with_creatives

# A new hook/message-angle experiment is naturally a top-of-funnel,
# attention-stage lever, so a product's TOF creative is preferred as the
# experiment's home context. MOF, then BOF, are used only when the product
# has no TOF creative to anchor against.
FUNNEL_STAGE_PREFERENCE = ["TOF", "MOF", "BOF"]

# The catalog's own label for the brand's current default proof-led claim.
# Used only as a control tie-breaking signal, never a hardcoded creative_id:
# select_control_creative falls through several rules before ever falling
# back to catalog order.
PROOF_MESSAGE_STYLE = "technical"
PROOF_HOOK_TYPES = {"proof", "education", "outcome"}

# The same metric pair the Intelligence Agent already uses to call a style
# "leading" (see message_style_leaders), so an experiment's own success bar
# doesn't quietly differ from how existing patterns are judged.
SUCCESS_METRICS = [
    "CTR, for whether the new hook earns more attention",
    "ROAS, for whether that attention converts as efficiently as the control",
    "CPA, as a secondary cost-efficiency check against the control",
]


def _humanize(value: str) -> str:
    """Display formatting only: "benefit_plus_proof" -> "benefit plus proof"."""
    return value.replace("_", " ")


@dataclass
class ExperimentProposal:
    """The Creative Strategist's structured output. A future live agent (an
    LLM call) would return this same shape; generated_by distinguishes
    which one produced a given instance. Every string field traces back to
    source_finding_id's evidence, control_creative_id's catalog row, or
    meta_ads.csv, never to an invented fact.

    confidence describes the strength of the evidence behind testing this,
    inherited from the source Finding: it is not a predicted result.
    """

    proposal_id: str
    source_finding_id: str
    title: str
    product: str
    funnel_stage: str
    customer_theme: str
    customer_insight: str
    performance_insight: str
    control_creative_id: str
    control_reason: str
    variable_to_test: str
    constant_elements: list[str]
    hypothesis: str
    proposed_direction: str
    success_metrics: list[str]
    confidence: str
    evidence: list[Evidence] = field(default_factory=list)
    generated_by: str = GENERATED_BY_PREVIEW


def experiment_worthy_findings(client_id: str) -> list[Finding]:
    """Findings from the Intelligence Brief worth developing into an
    experiment (see EXPERIMENT_WORTHY_TYPES). Uses the same top-3 window
    Marketing Intelligence itself shows, so Creative Lab never offers a
    finding the marketer couldn't also see on that page.
    """
    return [f for f in generate_findings(client_id, max_findings=3) if f.type in EXPERIMENT_WORTHY_TYPES]


def find_finding(client_id: str, finding_id: str) -> Finding | None:
    """The current Finding with this id, from the same top-3 window
    Marketing Intelligence shows, or None if it no longer resolves (e.g. the
    underlying data changed). Public so Creative Lab can render the source
    finding's own fields (type, title, why_it_matters) alongside the
    proposal built from it.
    """
    for finding in generate_findings(client_id, max_findings=3):
        if finding.finding_id == finding_id:
            return finding
    return None


def _select_funnel_stage(catalog: pd.DataFrame, product: str) -> str:
    available = set(catalog.loc[catalog["product_name"] == product, "funnel_stage"].unique())
    for stage in FUNNEL_STAGE_PREFERENCE:
        if stage in available:
            return stage
    raise ValueError(f"No creatives found for product {product!r}")


def select_control_creative(client_id: str, product: str, funnel_stage: str) -> tuple[pd.Series, str]:
    """Deterministically choose the existing creative that serves as the
    baseline for an experiment about `product` at `funnel_stage`.

    This is never a global "best ad": candidates are scoped to the same
    product and funnel stage the experiment is actually about, since a BOF
    discount ad and a TOF awareness ad have different jobs and aren't a fair
    baseline for each other.

    Within that scope, the rule tries, in order:
    1. The creative already carrying the product's technical/proof message
       style (PROOF_MESSAGE_STYLE), since that claim is what a message-angle
       experiment keeps constant while it changes the hook.
    2. The creative with an evidentiary hook type (PROOF_HOOK_TYPES), the
       closest available substitute when no creative uses the technical
       style directly.
    3. The strongest already-proven performer (highest ROAS among creatives
       that clear the Intelligence Agent's own volume floor), when neither
       proof signal is present.
    4. The lowest creative_id in the scope, a fully deterministic default so
       a control is always chosen.
    Ties within any rule break on highest ROAS, then lowest creative_id.
    """
    catalog = load_creative_catalog(client_id)
    candidates = catalog[(catalog["product_name"] == product) & (catalog["funnel_stage"] == funnel_stage)]
    if candidates.empty:
        raise ValueError(f"No creatives for {product!r} at funnel stage {funnel_stage!r}")

    joined = load_performance_with_creatives(client_id)
    by_creative = aggregate_performance(joined, by=["creative_id"]).set_index("creative_id")

    def roas(creative_id: str) -> float:
        if creative_id not in by_creative.index:
            return float("-inf")
        value = by_creative.loc[creative_id, "roas"]
        return float(value) if pd.notna(value) else float("-inf")

    def best_of(creative_ids: list[str]) -> pd.Series:
        best_id = sorted(creative_ids, key=lambda cid: (-roas(cid), cid))[0]
        return catalog.loc[catalog["creative_id"] == best_id].iloc[0]

    technical_ids = candidates.loc[candidates["message_style"] == PROOF_MESSAGE_STYLE, "creative_id"].tolist()
    if technical_ids:
        pick = best_of(technical_ids)
        reason = (
            f'"{pick["headline"]}" ({pick["creative_id"]}) is the existing {product} {funnel_stage} creative that '
            f'carries the product\'s technical/proof claim ({_humanize(PROOF_MESSAGE_STYLE)} message style), which '
            f"this experiment keeps constant while it changes the hook."
        )
        return pick, reason

    proof_hook_ids = candidates.loc[candidates["hook_type"].isin(PROOF_HOOK_TYPES), "creative_id"].tolist()
    if proof_hook_ids:
        pick = best_of(proof_hook_ids)
        reason = (
            f'"{pick["headline"]}" ({pick["creative_id"]}) is the existing {product} {funnel_stage} creative with '
            f'an evidentiary hook ({_humanize(pick["hook_type"])}), the closest existing claim to what this '
            f"experiment keeps constant while it changes the hook."
        )
        return pick, reason

    qualifying_ids = [
        cid
        for cid in candidates["creative_id"]
        if cid in by_creative.index
        and by_creative.loc[cid, "spend"] >= PERFORMANCE_MIN_SPEND
        and by_creative.loc[cid, "purchases"] >= PERFORMANCE_MIN_PURCHASES
    ]
    if qualifying_ids:
        pick = best_of(qualifying_ids)
        reason = (
            f'No creative in {product} {funnel_stage} carries an existing technical or evidentiary claim, so '
            f'"{pick["headline"]}" ({pick["creative_id"]}) is used instead: it is the strongest already-proven '
            f"performer in this context on {by_creative.loc[pick['creative_id'], 'roas']:.2f}x ROAS."
        )
        return pick, reason

    fallback_id = sorted(candidates["creative_id"])[0]
    pick = catalog.loc[catalog["creative_id"] == fallback_id].iloc[0]
    reason = (
        f"No creative in {product} {funnel_stage} carries an existing technical or evidentiary claim, and none "
        f'has enough volume to compare performance, so "{pick["headline"]}" ({pick["creative_id"]}) is used as the '
        f"default baseline already running in this context."
    )
    return pick, reason


def _customer_insight(finding: Finding) -> str:
    for evidence in finding.evidence:
        if evidence.label == "Customer signal volume":
            return evidence.detail
    return finding.summary


def _leader_detail(leader: dict) -> str:
    return (
        f"Within {leader['product_name']} {leader['funnel_stage']}, {_humanize(leader['leader_style'])} messaging "
        f"returns {leader['leader_roas']:.2f}x ROAS and {leader['leader_ctr']:.2%} CTR, versus "
        f"{leader['rest_best_roas']:.2f}x ROAS for the next-best qualifying style in that same context."
    )


def _leader_evidence(leader: dict, label: str) -> Evidence:
    return Evidence(
        label=label,
        detail=_leader_detail(leader),
        source="meta_ads.csv + creative_catalog.csv (core.analytics.aggregate_performance)",
        table=leader["cell_table"],
    )


def _select_performance_evidence(
    joined: pd.DataFrame, product: str, funnel_stage: str, theme_products: list[str]
) -> tuple[Evidence | None, str]:
    """Performance evidence for the EXACT (product, funnel_stage) this
    experiment is about, never evidence borrowed from a different funnel
    stage passed off as if it applied here: funnel-stage economics differ
    by design (a BOF retargeting cell and a TOF awareness cell aren't
    comparable), so a pattern from one is never presented as support for
    the other.

    Tries, in order:
    1. Direct: a qualifying message-style pattern in this exact cell. Real
       support for the experiment; returned as its own Evidence.
    2. Context: no qualifying pattern in this exact cell, but one exists
       somewhere else within the theme's broader associated-product scope
       (theme_products, the same scope the Intelligence Agent used when it
       surfaced this finding). Shown as background only, explicitly labeled
       as a different funnel stage and/or product, never as support.
    3. None: nothing qualifies even as context. Said honestly rather than
       reaching for the nearest available number.
    """
    direct = [leader for leader in message_style_leaders(joined, products=[product]) if leader["funnel_stage"] == funnel_stage]
    if direct:
        leader = direct[0]
        return _leader_evidence(leader, "Messaging performance"), _leader_detail(leader)

    broader = message_style_leaders(joined, products=theme_products)
    if broader:
        leader = broader[0]
        if leader["product_name"] == product:
            note = (
                f"No qualifying performance pattern exists for {product} {funnel_stage} specifically. For broader "
                f"context only: {_humanize(leader['leader_style'])} messaging leads {product} {leader['funnel_stage']} "
                f"at {leader['leader_roas']:.2f}x ROAS, but {leader['funnel_stage']} and {funnel_stage} have "
                f"different economics by design, so this is background, not support for this experiment."
            )
            label = "Messaging performance (broader context, different funnel stage)"
        else:
            note = (
                f"No qualifying performance pattern exists for {product} {funnel_stage}. A pattern exists for "
                f"{leader['product_name']} {leader['funnel_stage']} within this theme's broader context, but a "
                f"different product's performance is not used as support for this experiment."
            )
            label = "Messaging performance (broader context, different product)"
        return _leader_evidence(leader, label), note

    return None, (
        "No qualifying creative-performance pattern exists for this product and funnel stage, or anywhere in this "
        "theme's broader context. This proposal rests on the customer-signal and creative-coverage evidence above, "
        "not a performance comparison."
    )


def generate_proposal(client_id: str, finding_id: str) -> ExperimentProposal:
    """Turn one experiment-worthy Finding into a structured ExperimentProposal.

    Raises ValueError if finding_id doesn't resolve to a current,
    experiment-worthy finding for this client: Creative Lab is expected to
    catch this and fall back to letting the marketer choose from
    experiment_worthy_findings instead of showing a broken page.
    """
    finding = find_finding(client_id, finding_id)
    if finding is None:
        raise ValueError(f"No current finding {finding_id!r} for client {client_id!r}")
    if finding.type not in EXPERIMENT_WORTHY_TYPES:
        raise ValueError(f"Finding {finding_id!r} is a {finding.type!r}, which is not experiment-worthy")
    if not finding.products or not finding.themes:
        raise ValueError(f"Finding {finding_id!r} has no product or customer theme to build a hypothesis around")

    product = finding.products[0]
    theme = finding.themes[0]
    catalog = load_creative_catalog(client_id)
    funnel_stage = _select_funnel_stage(catalog, product)
    control, control_reason = select_control_creative(client_id, product, funnel_stage)
    control_style = _humanize(control["message_style"])

    hypothesis = (
        f'Leading {product} {funnel_stage} creative with a customer-language message about "{theme}", while '
        f"retaining the current ad's proof claim, may improve response compared with the {control_style} message "
        f"used today. This has not been tested for this angle and is a hypothesis to investigate, not a "
        f"guaranteed result."
    )
    proposed_direction = (
        f'Lead with a customer-language hook about "{theme}" for {product}, while keeping the current ad\'s CTA '
        f'("{control["cta"]}") and proof claim ("{control["primary_text"]}") unchanged.'
    )
    constant_elements = [
        f"Product: {product}",
        f"Funnel stage: {funnel_stage}",
        f'CTA: "{control["cta"]}"',
        f"Format: {control['format']}",
        f'Proof claim: "{control["primary_text"]}"',
    ]

    # The Finding's own "Messaging performance" evidence (if any) was chosen
    # by the Intelligence Agent across this theme's whole associated-product
    # scope, to support the Finding's own broader claim. It is not
    # necessarily about the exact (product, funnel_stage) this experiment
    # ends up testing, so it is never reused as-is here: performance
    # evidence for the proposal is always recomputed for this experiment's
    # own context (see _select_performance_evidence).
    joined = load_performance_with_creatives(client_id)
    performance_evidence, performance_insight = _select_performance_evidence(
        joined, product, funnel_stage, finding.products
    )
    non_performance_evidence = [e for e in finding.evidence if e.label != "Messaging performance"]

    evidence = non_performance_evidence.copy()
    if performance_evidence is not None:
        evidence.append(performance_evidence)
    evidence.append(
        Evidence(
            label="Control creative",
            detail=(
                f'{control["creative_id"]}: "{control["headline"]}" ({control_style} message style, '
                f'{_humanize(control["hook_type"])} hook), {funnel_stage} {product}.'
            ),
            source="creative_catalog.csv",
        )
    )

    return ExperimentProposal(
        proposal_id=f"proposal::{finding.finding_id}",
        source_finding_id=finding.finding_id,
        title=f'Test a "{theme}"-led hook for {product} ({funnel_stage})',
        product=product,
        funnel_stage=funnel_stage,
        customer_theme=theme,
        customer_insight=_customer_insight(finding),
        performance_insight=performance_insight,
        control_creative_id=control["creative_id"],
        control_reason=control_reason,
        variable_to_test="Primary message hook / opening claim",
        constant_elements=constant_elements,
        hypothesis=hypothesis,
        proposed_direction=proposed_direction,
        success_metrics=SUCCESS_METRICS,
        confidence=finding.confidence,
        evidence=evidence,
    )


# --- Creative Lab V2: Creative Opportunity (Milestone 22) -------------------
# A CreativeOpportunity is the Strategist's synthesis of ONE experiment-
# worthy Finding into a strategic territory a Creative Family can be built
# around: broader than a single ExperimentProposal (it does not commit to
# one variable-to-test wording or one ad package), narrower than the whole
# CreativePlan (agents/strategist/creative_plan.py, which combines every
# current opportunity plus cross-cutting context). Deliberately reuses
# _select_funnel_stage, select_control_creative, _customer_insight, and
# _select_performance_evidence rather than re-deriving any of that logic:
# the same product/funnel-stage-scoped baseline choice and the same
# context-preserving performance-evidence lookup apply here as they do to a
# single-finding ExperimentProposal.


@dataclass
class CreativeOpportunity:
    """The Strategist's structured read of one experiment-worthy Finding as
    a creative territory: not yet a specific ad, not yet a specific
    experiment, but the strategic frame (avatar, awareness stage, pain
    point, what to hold constant, what to test) that a Creative Family's
    concepts are all built to share. Every string traces back to
    source_finding_id's own evidence, creative_catalog.csv, or
    customer_signals.csv, exactly like ExperimentProposal.
    """

    opportunity_id: str
    source_finding_id: str
    title: str
    why_in_plan: str
    product: str
    funnel_stage: str
    avatar: str
    awareness_stage: str
    pain_point: str
    customer_insight: str
    performance_insight: str
    what_we_want_to_learn: str
    variable_to_test: str
    constants_to_preserve: list[str]
    control_creative_id: str
    control_reason: str
    confidence: str
    evidence: list[Evidence] = field(default_factory=list)
    generated_by: str = GENERATED_BY_PREVIEW


def _dominant_awareness_stage(client_id: str, theme: str) -> str:
    """The most common customer-signal intent label (customer_signals.csv:
    demo_intent_label, e.g. "problem_awareness", "research", "consideration")
    among signals mentioning this theme: the existing, already-labeled
    awareness taxonomy this project's demo data carries (see
    app_pages/signals.py's own display formatting of the same column),
    reused here rather than inventing a second one. "Unknown" only if no
    signal for this theme exists at all, never a guessed default.
    """
    signals = load_customer_signals(client_id)
    scoped = signals.loc[signals["demo_theme_label"] == theme, "demo_intent_label"]
    if scoped.empty:
        return "Unknown"
    mode = scoped.mode()
    if mode.empty:
        return "Unknown"
    return _humanize(mode.iloc[0]).capitalize()


def build_creative_opportunity(client_id: str, finding: Finding) -> CreativeOpportunity:
    """Turn one experiment-worthy Finding into a CreativeOpportunity: the
    same product/funnel-stage/control selection and evidence-preservation
    discipline as generate_proposal, but framed as a strategic territory
    (a learning QUESTION, a variable class, an avatar/awareness/pain-point
    strategy brief) rather than one committed hypothesis for one ad.
    Concept-level angles are built from this by
    agents.creative_studio.engine.generate_concepts_for_opportunity.

    Raises ValueError under the same conditions as generate_proposal (not
    experiment-worthy, or missing product/theme).
    """
    if finding.type not in EXPERIMENT_WORTHY_TYPES:
        raise ValueError(f"Finding {finding.finding_id!r} is a {finding.type!r}, which is not experiment-worthy")
    if not finding.products or not finding.themes:
        raise ValueError(f"Finding {finding.finding_id!r} has no product or customer theme to build a strategy around")

    product = finding.products[0]
    theme = finding.themes[0]
    catalog = load_creative_catalog(client_id)
    funnel_stage = _select_funnel_stage(catalog, product)
    control, control_reason = select_control_creative(client_id, product, funnel_stage)

    joined = load_performance_with_creatives(client_id)
    performance_evidence, performance_insight = _select_performance_evidence(
        joined, product, funnel_stage, finding.products
    )
    non_performance_evidence = [e for e in finding.evidence if e.label != "Messaging performance"]
    evidence = non_performance_evidence.copy()
    if performance_evidence is not None:
        evidence.append(performance_evidence)

    why_in_plan = f"{finding.summary} {finding.why_it_matters}"
    what_we_want_to_learn = (
        f'Whether a "{theme}"-led messaging angle for {product} {funnel_stage} earns more attention and converts '
        f"at least as well as the {_humanize(control['message_style'])} message running today, before committing "
        f"more budget to it. This is a question to test, not a predicted result."
    )
    constants_to_preserve = [
        f"Product: {product}",
        f"Funnel stage: {funnel_stage}",
        f'CTA: "{control["cta"]}"',
        f"Format: {control['format']}",
        f'Core approved product proof: "{control["primary_text"]}"',
    ]

    return CreativeOpportunity(
        opportunity_id=f"opportunity::{finding.finding_id}",
        source_finding_id=finding.finding_id,
        title=finding.title,
        why_in_plan=why_in_plan,
        product=product,
        funnel_stage=funnel_stage,
        avatar=f'{product} shoppers who bring up "{theme}"',
        awareness_stage=_dominant_awareness_stage(client_id, theme),
        pain_point=theme,
        customer_insight=_customer_insight(finding),
        performance_insight=performance_insight,
        what_we_want_to_learn=what_we_want_to_learn,
        variable_to_test="Messaging angle (opening claim / hook)",
        constants_to_preserve=constants_to_preserve,
        control_creative_id=control["creative_id"],
        control_reason=control_reason,
        confidence=finding.confidence,
        evidence=evidence,
    )


def build_creative_opportunities(client_id: str) -> list[CreativeOpportunity]:
    """One CreativeOpportunity per current experiment-worthy Finding (the
    same set experiment_worthy_findings already returns), in the same
    priority order generate_findings produces. Never more than one
    opportunity per finding, and never invents an opportunity with no
    backing finding.
    """
    return [build_creative_opportunity(client_id, finding) for finding in experiment_worthy_findings(client_id)]


def opportunity_to_proposal(opportunity: CreativeOpportunity) -> ExperimentProposal:
    """Adapt a CreativeOpportunity into the ExperimentProposal shape, purely
    so existing proposal-shaped consumers (agents.creative_studio.engine.
    build_control_ad_package) can be reused as-is instead of duplicated for
    the new opportunity/concept model. Never stored or shown as "the"
    proposal; a throwaway adapter object built fresh whenever one is needed.
    """
    return ExperimentProposal(
        proposal_id=opportunity.opportunity_id,
        source_finding_id=opportunity.source_finding_id,
        title=opportunity.title,
        product=opportunity.product,
        funnel_stage=opportunity.funnel_stage,
        customer_theme=opportunity.pain_point,
        customer_insight=opportunity.customer_insight,
        performance_insight=opportunity.performance_insight,
        control_creative_id=opportunity.control_creative_id,
        control_reason=opportunity.control_reason,
        variable_to_test=opportunity.variable_to_test,
        constant_elements=opportunity.constants_to_preserve,
        hypothesis=opportunity.what_we_want_to_learn,
        proposed_direction=opportunity.why_in_plan,
        success_metrics=SUCCESS_METRICS,
        confidence=opportunity.confidence,
        evidence=opportunity.evidence,
    )
