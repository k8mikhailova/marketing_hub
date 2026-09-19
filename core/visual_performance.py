"""Visual creative attributes joined with synthetic Meta performance, so
Creative Studio can ask "how have creatives with this visual trait
performed, in this exact product and funnel-stage context" and get either
a real, evidence-backed answer or an honest "not enough data," never a
manufactured one.

Provenance (see data/<client>/creative_visual_attributes.csv's own
data_type column): for the handful of creatives with a real local source
image, these attributes are our own structured analysis of what is
actually visible in that image (data_type="public_ad_observed_analysis").
For every other creative, they are deterministic demo metadata derived
from the creative's own catalog fields (data_type="demo_synthetic").
Neither is ever presented as Meta-provided data; Meta has no "visual
style" field. Performance stays exactly as synthetic as everywhere else in
this app: this module never treats a visual-attribute comparison as
anything more than a pattern in the demo dataset.

Reuses core.analytics.attribute_style_leaders (the same funnel-stage- and
product-scoped, volume-floored comparison agents/intelligence/engine.py's
message_style_leaders already uses for message style), so a visual
attribute is held to the identical evidence bar, not a looser one just
because a live model will eventually consume it.
"""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.analytics import (
    PERFORMANCE_MIN_PURCHASES,
    PERFORMANCE_MIN_RELATIVE_GAP,
    PERFORMANCE_MIN_SPEND,
    attribute_style_leaders,
)
from core.data import DATA_DIR, load_performance_with_creatives

# Kept intentionally small (compact taxonomy, not dozens of attributes):
# each is either a short categorical label or a boolean, one row per
# creative_id, joinable onto meta_ads.csv via creative_id like any other
# creative attribute.
VISUAL_ATTRIBUTES = [
    "human_present",
    "product_prominence",
    "water_or_glass_prominence",
    "text_density",
    "environment",
    "proof_visible",
]


def load_creative_visual_attributes(client_id: str) -> pd.DataFrame:
    """This client's visual taxonomy, one row per creative_id. Returns an
    empty (but correctly shaped) frame if the client has none yet, rather
    than raising, matching core/assets.py's own convention for a client
    with no optional data file.
    """
    path = DATA_DIR / client_id / "creative_visual_attributes.csv"
    if not path.exists():
        return pd.DataFrame(columns=["creative_id", *VISUAL_ATTRIBUTES, "data_type"])
    return pd.read_csv(path)


def load_performance_with_visuals(client_id: str) -> pd.DataFrame:
    """Meta performance joined to both the creative catalog (via
    core.data.load_performance_with_creatives) and this client's visual
    attributes, on creative_id. A creative with no visual-attribute row
    (shouldn't happen once every creative has one, but not assumed) simply
    gets NaN for the visual columns rather than being dropped.

    The catalog already has its own data_type column (always
    "demo_synthetic"); the visual attributes' own data_type (which
    distinguishes "public_ad_observed_analysis" from "demo_synthetic" per
    creative, see this module's own docstring) is renamed to
    visual_data_type before the merge so the two are never confused under
    pandas' automatic _x/_y suffixing.
    """
    joined = load_performance_with_creatives(client_id)
    visuals = load_creative_visual_attributes(client_id).rename(columns={"data_type": "visual_data_type"})
    return joined.merge(visuals, on="creative_id", how="left", validate="many_to_one")


@dataclass
class VisualPatternResult:
    """One visual-attribute comparison's outcome for one product/funnel-
    stage context: either a real, volume-backed pattern, or an honest
    statement of insufficient evidence. Never phrased as causal ("this
    visual causes better performance"): detail always reads as a
    historical/associative pattern, matching the same phrasing discipline
    agents/intelligence/engine.py already applies to message-style
    findings.
    """

    attribute: str
    product: str
    funnel_stage: str
    sufficient: bool
    detail: str
    leading_value: str | None = None
    leading_roas: float | None = None
    comparison_value: str | None = None
    comparison_roas: float | None = None
    cell_table: pd.DataFrame | None = None


def analyze_visual_attribute(client_id: str, attribute: str, product: str, funnel_stage: str) -> VisualPatternResult:
    """Compare performance across the distinct values of one visual
    attribute, scoped to exactly one product and funnel stage (never
    compares, say, Q60 BOF against Reverse Osmosis TOF and treats it as
    predictive: those have different economics by design, the same reason
    message_style_leaders never crosses that boundary either).

    Returns sufficient=False, with a reason in detail, when: the attribute
    isn't recognized, no creatives exist in this exact context, fewer than
    2 distinct values of the attribute clear the volume floor in this
    context, or no value's win is clean on both ROAS and CTR with a real
    (non-noise) gap. Only returns sufficient=True with an actual result
    when attribute_style_leaders finds a qualifying pattern.
    """
    if attribute not in VISUAL_ATTRIBUTES:
        return VisualPatternResult(
            attribute=attribute,
            product=product,
            funnel_stage=funnel_stage,
            sufficient=False,
            detail=f'"{attribute}" is not a recognized visual attribute.',
        )

    joined = load_performance_with_visuals(client_id)
    scoped = joined[(joined["product_name"] == product) & (joined["funnel_stage"] == funnel_stage)]
    if scoped.empty:
        return VisualPatternResult(
            attribute=attribute,
            product=product,
            funnel_stage=funnel_stage,
            sufficient=False,
            detail=f"No creatives found for {product} at {funnel_stage}.",
        )

    leaders = attribute_style_leaders(
        scoped,
        attribute,
        products=[product],
        min_spend=PERFORMANCE_MIN_SPEND,
        min_purchases=PERFORMANCE_MIN_PURCHASES,
        min_relative_gap=PERFORMANCE_MIN_RELATIVE_GAP,
    )
    matching = [leader for leader in leaders if leader["funnel_stage"] == funnel_stage]
    if not matching:
        distinct_values = scoped[attribute].nunique(dropna=True)
        if distinct_values < 2:
            reason = f'Only one observed value of "{attribute}" exists for {product} {funnel_stage}: no comparison is possible.'
        else:
            reason = (
                f'"{attribute}" values for {product} {funnel_stage} don\'t clear the volume floor '
                f"(${PERFORMANCE_MIN_SPEND:,.0f} spend, {PERFORMANCE_MIN_PURCHASES:.0f} purchases) or don't show "
                f"a clean, non-noise difference on both ROAS and CTR."
            )
        return VisualPatternResult(
            attribute=attribute, product=product, funnel_stage=funnel_stage, sufficient=False, detail=reason
        )

    leader = matching[0]
    detail = (
        f'Within {product} {funnel_stage}, creatives where {attribute.replace("_", " ")} is '
        f'"{leader["leader_value"]}" have historically returned {leader["leader_roas"]:.2f}x ROAS and '
        f'{leader["leader_ctr"]:.2%} CTR, versus {leader["rest_best_roas"]:.2f}x ROAS for creatives where it is '
        f'"{leader["runner_up_value"]}" in that same context. This is a historical pattern in the demo data, not '
        f"a claim that this visual trait causes the difference."
    )
    return VisualPatternResult(
        attribute=attribute,
        product=product,
        funnel_stage=funnel_stage,
        sufficient=True,
        detail=detail,
        leading_value=str(leader["leader_value"]),
        leading_roas=float(leader["leader_roas"]),
        comparison_value=str(leader["runner_up_value"]),
        comparison_roas=float(leader["rest_best_roas"]),
        cell_table=leader["cell_table"],
    )


def visual_performance_context(client_id: str, product: str, funnel_stage: str) -> list[VisualPatternResult]:
    """Run analyze_visual_attribute for every attribute in VISUAL_ATTRIBUTES
    in this one product/funnel-stage context, so a caller (Creative Studio)
    gets one list to work from instead of calling the single-attribute
    function 6 times itself. Includes insufficient-evidence results too
    (callers should filter on .sufficient, not assume every entry is a
    real pattern), so a caller can see what was actually checked.
    """
    return [analyze_visual_attribute(client_id, attribute, product, funnel_stage) for attribute in VISUAL_ATTRIBUTES]


def attribute_value_provenance(client_id: str, attribute: str, product: str, funnel_stage: str, value) -> str:
    """Whether the creatives behind one attribute-value cell (e.g.
    human_present=True for Reverse Osmosis Systems/MOF) include any
    independently reviewed source image, or are entirely heuristically
    derived demo metadata (see this module's own docstring on the two
    data_type tiers). Returns "observed" (every qualifying creative is
    public_ad_observed_analysis), "synthetic" (every one is demo_synthetic,
    or none exist), or "mixed". A caller (Creative Studio) uses this to
    avoid presenting a heuristic-only pattern with the same confidence as
    one backed by an actually-reviewed image; it never changes whether a
    pattern counts as sufficient, only how it should be described.
    """
    joined = load_performance_with_visuals(client_id)
    scoped = joined[
        (joined["product_name"] == product) & (joined["funnel_stage"] == funnel_stage) & (joined[attribute] == value)
    ]
    data_types = set(scoped["visual_data_type"].dropna().unique())
    if not data_types or data_types == {"demo_synthetic"}:
        return "synthetic"
    if data_types == {"public_ad_observed_analysis"}:
        return "observed"
    return "mixed"
