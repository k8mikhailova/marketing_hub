"""Deterministic preview insight logic for the Overview page.

These functions stand in for what the Intelligence, Performance, and
Creative Strategist agents will eventually produce. Everything here is
arithmetic over the existing datasets, no LLM, no hardcoded conclusion.
Each function recomputes from data every call, so if the underlying CSVs
changed, the headline would change with them; nothing here is a canned
sentence with numbers dropped in.

If a function's evidence bar isn't cleared, it returns found=False with a
plain explanation instead of forcing a conclusion the data doesn't support.
This is explicitly *not* the Intelligence/Performance/Strategist agents:
those get built later, informed by (and likely replacing) this logic.
"""
from dataclasses import dataclass, field

import pandas as pd

from core.creative_coverage import CUSTOMER_THEME_TO_CREATIVE_KEYWORDS, classify_theme_emphasis
from core.data import load_creative_catalog, load_customer_signals, load_performance_with_creatives

# Noise floors, chosen so a headline never rests on a handful of rows.
EMERGING_SIGNAL_MIN_RECENT_COUNT = 5  # a "growing" theme must have at least this many mentions recently
WINNING_PATTERN_MIN_SPEND = 1500.0  # below this, a single creative could swing the whole angle's ROAS
WINNING_PATTERN_MIN_PURCHASES = 15  # avoid crowning a pattern built on a handful of conversions
WINNING_PATTERN_MIN_RELATIVE_GAP = 0.10  # a CTR or ROAS difference under 10% is noise, not a real tradeoff

# A theme must clear this floor to count as "prominent": with 240 signals,
# 8% is ~19 mentions, not a handful.
OPPORTUNITY_MIN_SIGNAL_SHARE = 0.08
# A theme must lead fewer than a third of its product's relevant creatives to
# count as "rarely the primary hook." Above that, it's already well covered.
OPPORTUNITY_MAX_PRIMARY_HOOK_RATIO = 1 / 3

# The theme -> creative-copy-keyword taxonomy now lives in
# core/creative_coverage.py (CUSTOMER_THEME_TO_CREATIVE_KEYWORDS), shared
# with the Intelligence Agent's evidence-building code so there is exactly
# one definition of "does this creative address this theme."


@dataclass
class Insight:
    found: bool
    headline: str
    explanation: str
    evidence_lines: list[str] = field(default_factory=list)
    evidence_table: pd.DataFrame | None = None
    # Structured payload for callers that need a value this insight is about
    # (e.g. a product name, to look up a creative image) without parsing it
    # back out of the headline text.
    data: dict = field(default_factory=dict)


def emerging_signal(client_id: str) -> Insight:
    """Which customer-conversation theme moved the most, and in which direction.

    Splits the available signal history into two equal halves by date and
    compares per-theme counts. The theme with the largest absolute increase
    wins, provided its recent count clears a noise floor (comparing tiny
    counts by percentage would let a 1-to-3-mention theme look "explosive").
    If no theme grew meaningfully, falls back to the single most-mentioned
    theme overall, explicitly labeled "prominent" rather than "emerging"
    since growth wasn't the evidence.
    """
    signals = load_customer_signals(client_id)
    if signals.empty:
        return Insight(False, "No customer signals yet", "No signal data is available for this client.")

    midpoint = signals["date"].min() + (signals["date"].max() - signals["date"].min()) / 2
    first_half = signals[signals["date"] <= midpoint]
    second_half = signals[signals["date"] > midpoint]

    counts = pd.DataFrame(
        {
            "first_half": first_half["demo_theme_label"].value_counts(),
            "second_half": second_half["demo_theme_label"].value_counts(),
        }
    ).fillna(0)
    counts["delta"] = counts["second_half"] - counts["first_half"]

    growing = counts[counts["second_half"] >= EMERGING_SIGNAL_MIN_RECENT_COUNT]
    growing = growing[growing["delta"] > 0].sort_values("delta", ascending=False)

    evidence_table = counts.sort_values("delta", ascending=False).reset_index()
    evidence_table.columns = ["theme", "first_half_count", "second_half_count", "change"]

    first_date = signals["date"].min().date()
    mid_date = midpoint.date()
    last_date = signals["date"].max().date()

    if not growing.empty:
        theme = growing.index[0]
        row = growing.iloc[0]
        return Insight(
            found=True,
            headline=f'"{theme}" is a growing conversation theme',
            explanation=(
                f'Mentions of "{theme}" rose from {int(row["first_half"])} to '
                f'{int(row["second_half"])} between the first and second half of the '
                f"available signal history, the largest increase of any theme."
            ),
            evidence_lines=[
                f"Window: {first_date}–{mid_date} vs {mid_date}–{last_date}",
                f'"{theme}": {int(row["first_half"])} → {int(row["second_half"])} mentions '
                f'({int(row["delta"]):+d})',
                f"Compared across {counts.shape[0]} customer-conversation themes, {len(signals)} total signals.",
            ],
            evidence_table=evidence_table,
            data={
                "kind": "growth",
                "theme": theme,
                "first_half": int(row["first_half"]),
                "second_half": int(row["second_half"]),
                "delta": int(row["delta"]),
            },
        )

    # No theme cleared the growth bar: report prominence instead of a fabricated trend.
    totals = signals["demo_theme_label"].value_counts()
    top_theme = totals.index[0]
    return Insight(
        found=True,
        headline=f'"{top_theme}" remains the most prominent theme',
        explanation=(
            f'No theme showed a clear increase this period, so this reflects overall '
            f'volume rather than a trend: "{top_theme}" accounts for {int(totals.iloc[0])} '
            f"of {len(signals)} signals."
        ),
        evidence_lines=[
            f"Window: {first_date}–{last_date}",
            f'"{top_theme}": {int(totals.iloc[0])} of {len(signals)} total signals',
        ],
        evidence_table=evidence_table,
        data={"kind": "prominence", "theme": top_theme, "count": int(totals.iloc[0]), "total": len(signals)},
    )


def _angle_metrics(joined: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    grouped = joined.groupby(group_cols, as_index=False).agg(
        spend=("spend", "sum"),
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        purchases=("purchases", "sum"),
        revenue=("revenue", "sum"),
    )
    grouped["ctr"] = grouped["clicks"] / grouped["impressions"]
    grouped["cpa"] = grouped["spend"] / grouped["purchases"]
    grouped["roas"] = grouped["revenue"] / grouped["spend"]
    return grouped


def winning_pattern(client_id: str) -> Insight:
    """A genuine attention-vs-efficiency tradeoff between creative angles for
    the same product and funnel stage, never a single "biggest ROAS" pick.

    Comparing angles across products or funnel stages isn't fair (a BOF
    retargeting offer and a TOF awareness creative have different economics
    by design, and different products serve different intents), so every
    comparison here is within one (product, funnel_stage) cell: the
    tightest genuinely comparable context this data supports.

    Within that cell, this looks for two *different* angles that each lead
    on a different metric: one earning more attention (higher CTR), the
    other converting it more efficiently (higher ROAS / lower CPA), rather
    than crowning whichever angle has the single highest ROAS. A one-sided
    "biggest lift" mostly just confirms that promotional or retargeting
    creative converts well at the bottom of the funnel, which isn't a new
    or actionable pattern. Both the CTR gap and the ROAS gap must clear a
    10% relative floor, so two angles that are effectively tied don't get
    reported as a meaningful tradeoff.

    If no (product, funnel_stage) cell shows this kind of tradeoff, falls
    back to the single angle most outperforming its peers within the same
    product and funnel stage (still never compared outside that context),
    and if nothing clears that bar either, says so plainly.
    """
    joined = load_performance_with_creatives(client_id)
    if joined.empty:
        return Insight(False, "No performance data yet", "No Meta performance data is available for this client.")

    by_pfa = _angle_metrics(joined, ["product_name", "funnel_stage", "creative_angle"])
    candidates = by_pfa[
        (by_pfa["spend"] >= WINNING_PATTERN_MIN_SPEND) & (by_pfa["purchases"] >= WINNING_PATTERN_MIN_PURCHASES)
    ].copy()

    tradeoffs = []
    for (product, stage), group in candidates.groupby(["product_name", "funnel_stage"]):
        if len(group) < 2:
            continue
        ctr_leader = group.loc[group["ctr"].idxmax()]
        roas_leader = group.loc[group["roas"].idxmax()]
        if ctr_leader["creative_angle"] == roas_leader["creative_angle"]:
            continue  # one angle wins both, not a tradeoff
        if roas_leader["ctr"] <= 0 or ctr_leader["roas"] <= 0:
            continue
        ctr_gap = (ctr_leader["ctr"] - roas_leader["ctr"]) / roas_leader["ctr"]
        roas_gap = (roas_leader["roas"] - ctr_leader["roas"]) / ctr_leader["roas"]
        if ctr_gap < WINNING_PATTERN_MIN_RELATIVE_GAP or roas_gap < WINNING_PATTERN_MIN_RELATIVE_GAP:
            continue
        tradeoffs.append(
            {
                "product_name": product,
                "funnel_stage": stage,
                "attention_angle": ctr_leader["creative_angle"],
                "efficiency_angle": roas_leader["creative_angle"],
                "ctr_gap": ctr_gap,
                "roas_gap": roas_gap,
                "strength": min(ctr_gap, roas_gap),
                "context_table": group[["creative_angle", "spend", "purchases", "ctr", "cpa", "roas"]],
            }
        )

    if tradeoffs:
        best = max(tradeoffs, key=lambda r: r["strength"])
        context = best["context_table"].sort_values("roas", ascending=False).reset_index(drop=True)
        att = context[context["creative_angle"] == best["attention_angle"]].iloc[0]
        eff = context[context["creative_angle"] == best["efficiency_angle"]].iloc[0]
        return Insight(
            found=True,
            headline=(
                f'Within {best["product_name"]} · {best["funnel_stage"]}, "{best["attention_angle"]}" '
                f'earns more attention while "{best["efficiency_angle"]}" converts it more efficiently'
            ),
            explanation=(
                f'"{best["attention_angle"]}" gets a higher CTR ({att["ctr"]:.2%} vs {eff["ctr"]:.2%}) than '
                f'"{best["efficiency_angle"]}", but "{best["efficiency_angle"]}" converts that attention far '
                f'more efficiently: {eff["roas"]:.2f}x ROAS (${eff["cpa"]:,.2f} CPA) versus {att["roas"]:.2f}x '
                f'ROAS (${att["cpa"]:,.2f} CPA). Neither angle wins on both dimensions within '
                f'{best["product_name"]} · {best["funnel_stage"]}.'
            ),
            evidence_lines=[
                f"Context: {best['product_name']} · {best['funnel_stage']}",
                f'{best["attention_angle"]}: ${att["spend"]:,.0f} spend, {int(att["purchases"])} purchases, '
                f'CTR {att["ctr"]:.2%}, CPA ${att["cpa"]:,.2f}, ROAS {att["roas"]:.2f}x',
                f'{best["efficiency_angle"]}: ${eff["spend"]:,.0f} spend, {int(eff["purchases"])} purchases, '
                f'CTR {eff["ctr"]:.2%}, CPA ${eff["cpa"]:,.2f}, ROAS {eff["roas"]:.2f}x',
            ],
            evidence_table=context,
            data={
                "kind": "tradeoff",
                "context": f'{best["product_name"]} · {best["funnel_stage"]}',
                "attention_angle": best["attention_angle"],
                "efficiency_angle": best["efficiency_angle"],
                "attention": {"ctr": float(att["ctr"]), "roas": float(att["roas"]), "cpa": float(att["cpa"])},
                "efficiency": {"ctr": float(eff["ctr"]), "roas": float(eff["roas"]), "cpa": float(eff["cpa"])},
                "interpretation": (
                    f'"{best["attention_angle"]}" earns more attention; '
                    f'"{best["efficiency_angle"]}" converts more efficiently.'
                ),
            },
        )

    # No tradeoff found, fall back to the best single outperformer within
    # its own product + funnel stage (never compared outside that context).
    fallback_rows = []
    for _, row in candidates.iterrows():
        product, stage, angle = row["product_name"], row["funnel_stage"], row["creative_angle"]
        rest = joined[
            (joined["product_name"] == product)
            & (joined["funnel_stage"] == stage)
            & (joined["creative_angle"] != angle)
        ]
        rest_spend = rest["spend"].sum()
        if rest_spend <= 0:
            continue
        rest_roas = rest["revenue"].sum() / rest_spend
        if rest_roas <= 0:
            continue
        fallback_rows.append(
            {
                "product_name": product,
                "funnel_stage": stage,
                "creative_angle": angle,
                "spend": row["spend"],
                "purchases": row["purchases"],
                "ctr": row["ctr"],
                "cpa": row["cpa"],
                "roas": row["roas"],
                "rest_of_context_roas": rest_roas,
                "lift": row["roas"] / rest_roas,
            }
        )

    if not fallback_rows:
        return Insight(
            found=False,
            headline="No reliable performance pattern yet",
            explanation=(
                "No creative angle has enough spend and purchases within a single "
                "product and funnel stage to compare it fairly against its peers."
            ),
        )

    lift_df = pd.DataFrame(fallback_rows).sort_values("lift", ascending=False).reset_index(drop=True)
    best = lift_df.iloc[0]
    if best["lift"] <= 1.0:
        return Insight(
            found=False,
            headline="No creative angle is clearly outperforming within its product and funnel stage",
            explanation="Every angle with enough volume performs in line with (or below) its peers in the same context.",
            evidence_table=lift_df,
        )

    return Insight(
        found=True,
        headline=f'Within {best["product_name"]} · {best["funnel_stage"]}, "{best["creative_angle"]}" is outperforming',
        explanation=(
            f'"{best["creative_angle"]}" creatives return {best["roas"]:.2f}x ROAS versus '
            f'{best["rest_of_context_roas"]:.2f}x for the rest of {best["product_name"]} · {best["funnel_stage"]} '
            f"({best['lift']:.1f}x the peer average), compared only within the same product and funnel stage."
        ),
        evidence_lines=[
            f"Context: {best['product_name']} · {best['funnel_stage']}",
            f"{best['creative_angle']}: ${best['spend']:,.0f} spend, {int(best['purchases'])} purchases, "
            f"CTR {best['ctr']:.2%}, CPA ${best['cpa']:,.2f}, ROAS {best['roas']:.2f}x",
            f"Rest of context: {best['rest_of_context_roas']:.2f}x ROAS",
        ],
        evidence_table=lift_df,
        data={
            "kind": "outperformance",
            "context": f'{best["product_name"]} · {best["funnel_stage"]}',
            "angle": best["creative_angle"],
            "roas": float(best["roas"]),
            "rest_roas": float(best["rest_of_context_roas"]),
            "lift": float(best["lift"]),
        },
    )


def next_opportunity(client_id: str) -> Insight:
    """A customer-conversation theme our creative rarely leads with.

    Answers "what are customers repeatedly talking about that our current
    creative is not emphasizing enough?" rather than comparing signal share
    to spend share directly (which aren't comparable enough to imply an
    opportunity on their own).

    For each customer-signal theme (demo_theme_label), finds the product
    customers most associate it with (its most common product_context), then
    checks that product's own creative catalog for the theme using
    core/creative_coverage.py's shared, explicit keyword taxonomy, never
    keyword logic invented ad hoc here. A theme qualifies as an opportunity
    only if it's a meaningful share of all customer signals (not a fringe
    topic) *and* rarely appears as a creative's primary hook (headline) for
    its product. Being mentioned in supporting copy doesn't disqualify it:
    the gap is specifically about what leads the message, not whether the
    topic is addressed at all. Among qualifying themes, the most-discussed
    one is reported. This is phrased as a hypothesis worth testing, not a
    causal claim: the theme's conversation volume doesn't prove a taste-led
    (or any other) creative would perform better, only that it's untested.
    """
    signals = load_customer_signals(client_id)
    catalog = load_creative_catalog(client_id)
    if signals.empty or catalog.empty:
        return Insight(False, "Not enough data yet", "Signal or creative data is missing for this client.")

    total_signals = len(signals)
    theme_counts = signals["demo_theme_label"].value_counts()
    dominant_product = signals.groupby("demo_theme_label")["product_context"].agg(lambda s: s.value_counts().idxmax())

    rows = []
    breakdowns = {}
    for theme in CUSTOMER_THEME_TO_CREATIVE_KEYWORDS:
        if theme not in theme_counts.index:
            continue
        product = dominant_product[theme]
        classified = classify_theme_emphasis(catalog, theme, products=[product])
        if classified.empty:
            continue

        counts = classified["emphasis"].value_counts()
        z = len(classified)
        y = int(counts.get("primary_hook", 0))
        m = int(counts.get("mentioned", 0))
        signal_share = theme_counts[theme] / total_signals

        rows.append(
            {
                "theme": theme,
                "signal_count": int(theme_counts[theme]),
                "signal_share": signal_share,
                "dominant_product": product,
                "relevant_creatives": z,
                "primary_hook_count": y,
                "mentioned_count": m,
                "absent_count": z - y - m,
                "primary_hook_ratio": y / z,
            }
        )
        breakdowns[theme] = classified

    if not rows:
        return Insight(
            False,
            "No themes to compare yet",
            "No customer-signal theme could be matched to a product's creative catalog.",
        )

    summary = pd.DataFrame(rows).sort_values("signal_share", ascending=False).reset_index(drop=True)

    qualifying = summary[
        (summary["signal_share"] >= OPPORTUNITY_MIN_SIGNAL_SHARE)
        & (summary["primary_hook_ratio"] <= OPPORTUNITY_MAX_PRIMARY_HOOK_RATIO)
    ]

    if qualifying.empty:
        return Insight(
            found=False,
            headline="No clear messaging gap found",
            explanation=(
                "Every theme that comes up meaningfully in customer signals is already a primary "
                "creative hook often enough, or no theme has enough signal volume to act on."
            ),
            evidence_table=summary,
        )

    best = qualifying.iloc[0]
    theme = best["theme"]
    classified = breakdowns[theme]
    mentioned_ids = classified.loc[classified["emphasis"] == "mentioned", "creative_id"].tolist()
    hook_ids = classified.loc[classified["emphasis"] == "primary_hook", "creative_id"].tolist()

    if best["primary_hook_count"] > 0:
        hook_clause = f'only {best["primary_hook_count"]} of {best["relevant_creatives"]} use it as the primary message'
    else:
        hook_clause = f'none of the {best["relevant_creatives"]} use it as the primary message'
    if best["mentioned_count"] > 0:
        mention_clause = f' ({best["mentioned_count"]} mention it in supporting copy)'
    else:
        mention_clause = ""

    # Derived, not assumed: note if the product's own creative toolkit already
    # includes proof-style messaging worth carrying into a new concept.
    relevant_catalog = catalog[catalog["product_name"] == best["dominant_product"]]
    has_proof = relevant_catalog["hook_type"].eq("proof").any() or relevant_catalog["message_style"].str.contains(
        "proof", na=False
    ).any()
    retain_clause = ", while retaining proof-based credibility" if has_proof else ""

    return Insight(
        found=True,
        headline=f'"{theme}" is prominent in customer conversation but rarely leads {best["dominant_product"]} creative',
        explanation=(
            f'"{theme}" represents {best["signal_share"]:.0%} of customer signals, but among '
            f'{best["dominant_product"]} creatives, {hook_clause}{mention_clause}. Consider testing a '
            f'"{theme}"-led concept for {best["dominant_product"]}{retain_clause}.'
        ),
        evidence_lines=[
            f'{theme}: {best["signal_count"]} of {total_signals} customer signals ({best["signal_share"]:.0%})',
            f'Dominant product for this theme: {best["dominant_product"]}',
            f'Primary hook in {best["relevant_creatives"]} relevant creatives: {best["primary_hook_count"]}'
            + (f" ({', '.join(hook_ids)})" if hook_ids else ""),
            f'Mentioned in supporting copy only: {best["mentioned_count"]}'
            + (f" ({', '.join(mentioned_ids)})" if mentioned_ids else ""),
            f'Absent from copy entirely: {best["absent_count"]}',
        ],
        evidence_table=summary,
        data={
            "kind": "messaging_gap",
            "theme": theme,
            "product": best["dominant_product"],
            "signal_share": float(best["signal_share"]),
            "relevant_creatives": int(best["relevant_creatives"]),
            "primary_hook_count": int(best["primary_hook_count"]),
            "mentioned_count": int(best["mentioned_count"]),
            "recommendation": f'Test a "{theme}"-led concept for {best["dominant_product"]}{retain_clause}.',
        },
    )
