"""Deterministic, Python-owned synthetic performance simulation for one
prepared experiment's demo test (Milestone 17A: the result DATA MODEL and
its numbers, not the Performance Agent's interpretation of them, which is
future work).

Core principle: this module must NOT guarantee that an AI-generated
creative beats the current ad. A real A/B test can produce a clear winner,
a mixed result (one metric up, another down), a neutral result, or a
clear loser, and the demo has to be capable of all four, or "we tested it
and it improved" would be a foregone conclusion rather than something
worth actually testing. Every number here is derived by fixed arithmetic
rules from data already in this project (real historical Meta performance,
a real message-style evidence check) plus a deterministic, hash-seeded
per-creative variation, never an LLM call and never wall-clock randomness:
the same experiment handoff always produces the exact same
ExperimentResult, every time, forever.

Methodology, in order:

1. Test-period normalization. The current ad's REAL historical aggregate
   (data/<client>/meta_ads.csv, spend/impressions/clicks/purchases/revenue
   summed over its full history) is rescaled to a fixed, fair per-creative
   test budget (`_test_spend`: this creative's own real daily spend rate
   times DEMO_TEST_DAYS), applied identically to the current ad and every
   new creative. Rescaling multiplies every raw count by the same factor,
   so the current ad's real rates (CTR, CPA, ROAS) are preserved exactly;
   only the absolute volume changes, to a level actually comparable across
   variants with no history of their own. This is a normalized test-period
   projection, clearly not additional real Meta data.
2. A modest, evidence-gated group tilt. `_evidence_tilt` reuses
   core.analytics.attribute_style_leaders, the exact same volume-floored,
   funnel-stage-scoped comparison Marketing Intelligence and Milestone
   15.1's visual-evidence seam already use, to check whether
   "customer_language" message-style creatives have a real, sufficient,
   qualifying performance edge for this control's own product and funnel
   stage. If yes, every new creative's simulated rates get a small,
   uniform uplift (EVIDENCE_TILT); if the evidence is insufficient (as it
   genuinely is for some real contexts in this dataset), there is no tilt
   at all, exactly matching the "insufficient evidence, don't force a
   pattern" discipline already established. This is never per-creative and
   never claims a visual/message trait caused a specific number; it only
   says the underlying hypothesis has, or doesn't have, real grounding in
   this demo's own data.
3. Deterministic per-creative variation. Each new creative's own stable
   generated_id seeds two independent uniform draws (CTR and conversion-
   rate multipliers, via Python's `random.Random` with a sha256-derived
   integer seed, never `random` module global state and never a wall-clock
   seed), applied on top of the current ad's own real rates and the group
   tilt. Two independent multipliers (not one combined one) are what makes
   "improves CTR but hurts conversion" a real possible outcome, not just
   uniformly better or worse. The wide, deliberately unbounded-above-1.0
   ranges (see CTR_MULTIPLIER_RANGE / CVR_MULTIPLIER_RANGE) mean a given
   batch can plausibly land anywhere from a clear loser to a clear winner;
   nothing here nudges the draw toward success.
4. Mathematical consistency by construction. Every creative's impressions,
   clicks, and purchases are computed as whole-number COUNTS first (from
   the rates above); ctr/cpa/roas are then DERIVED from those same counts
   (ctr = clicks/impressions, cpa = spend/purchases, roas =
   revenue/spend), never invented independently, so a rate can never
   contradict its own underlying counts. A zero denominator (e.g. zero
   purchases) yields None for that one derived value, not a manufactured
   0.0 or a crash: "no purchases" is fundamentally different from "$0
   cost per purchase."

Isolated demo fixture: EVIDENCE_TILT's own numeric value is a fixed
choice for this demo (documented right where it's defined), not a
generalizable inference; the mechanism that decides WHETHER to apply it
(real, volume-floored evidence) is general and applies to any client's
data, never a hardcoded product or creative id.
"""
import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.analytics import (
    PERFORMANCE_MIN_PURCHASES,
    PERFORMANCE_MIN_RELATIVE_GAP,
    PERFORMANCE_MIN_SPEND,
    aggregate_performance,
    attribute_style_leaders,
)
from core.data import load_creative_catalog, load_meta_ads, load_performance_with_creatives

DATA_TYPE_DEMO_SYNTHETIC = "demo_synthetic"

# The length of the simulated test window: a fixed demo assumption (not
# derived from evidence), documented here so it's never mistaken for a
# real Meta flight length. Combined with a creative's own real daily
# spend rate, it sets one fair, comparable test budget for every variant.
# 30 days (not, say, 7) is itself a demo-legibility choice: this dataset's
# lower-volume creatives can have single-digit purchases over their full
# 60-day history, and a shorter test window would push several simulated
# creatives to 0-1 purchases, which is technically fine (None-handled, not
# a crash) but reads as sparse/noisy rather than a legible demo result.
DEMO_TEST_DAYS = 30

# A creative-level CTR/conversion-rate multiplier is drawn uniformly from
# these ranges (see _deterministic_uniform): wide enough, and centered
# close enough to 1.0, that a real demo batch can land anywhere from a
# clear loser (low end of both) to a clear winner (high end of both), with
# "improves one metric, hurts the other" a normal, expected outcome, not
# an edge case. Isolated demo fixture values: chosen to make this specific
# 6-strategy, single-client demo behave narratively well, not derived from
# a formula, and not something a future, differently-shaped dataset should
# assume still applies.
CTR_MULTIPLIER_RANGE = (0.70, 1.40)
CVR_MULTIPLIER_RANGE = (0.65, 1.45)

# The modest, isolated-demo-fixture uplift applied to BOTH multiplier
# ranges, and only to the whole new-creative batch at once, when
# _evidence_tilt finds real, sufficient message-style evidence favoring
# customer-language messaging for this control's own product/funnel
# stage. 1.0 (no tilt at all) otherwise: never forces a favorable
# tilt when the evidence doesn't support one.
EVIDENCE_TILT = 1.08


@dataclass
class CreativeResult:
    """One creative's simulated demo-test performance: the current ad's
    own real-history-derived test-period result, or one new creative's
    fully synthetic one. Every rate (ctr/cpa/roas) is derived from the
    count fields on this SAME object, never set independently; a rate is
    None only when its denominator was truly zero (see this module's own
    docstring), never a silently wrong 0.0.
    """

    creative_id: str
    role: str  # "current" | "new"
    name: str
    image_path: str | None
    spend: float
    impressions: int
    clicks: int
    purchases: int
    revenue: float
    ctr: float | None
    cpa: float | None
    roas: float | None


@dataclass
class ExperimentResult:
    """One prepared experiment's complete demo-test outcome: current_
    ad_result plus one CreativeResult per selected new creative, never
    collapsed into a single treatment-wide average, since the whole point
    is to learn which individual execution performed how. Built once, by
    build_experiment_result or build_concept_arms_result, from a handoff
    dict alone; nothing here is regenerated on a rerender, and nothing
    here was produced by an LLM, an image-provider call, or a paid API of
    any kind.

    Structured so a Performance Agent can consume it directly:
    current_ad_result and treatment_results are already typed
    CreativeResult objects with self-consistent counts and rates, not
    values that agent would need to scrape back out of rendered Streamlit
    widgets.

    Milestone 23: current_ad_result is now Optional. The OLD experiment
    type (build_experiment_result) always populates a real baseline
    result here, unchanged. The NEW Creative Lab V2 experiment type
    (build_concept_arms_result) sets this to None: that experiment
    compares several Creative Concepts against EACH OTHER (against the
    group's own mean, see agents/performance/engine.py::
    analyze_concept_experiment), not against a mandatory current-ad
    baseline, so treatment_results holds every experiment ARM and there is
    no "current" row to report. A None here is a deliberate fact ("this
    experiment has no baseline arm"), never a missing/uninitialized value.
    """

    experiment_id: str
    client_id: str
    generated_at: str
    current_ad_result: CreativeResult | None
    treatment_results: list[CreativeResult] = field(default_factory=list)
    status: str = "completed"
    data_type: str = DATA_TYPE_DEMO_SYNTHETIC


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def _seed_for(*parts: str) -> int:
    digest = hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _deterministic_uniform(seed_key: str, low: float, high: float) -> float:
    return random.Random(_seed_for(seed_key)).uniform(low, high)


def _real_creative_aggregate(client_id: str, creative_id: str) -> dict:
    """This creative's REAL, full-history aggregate (spend, impressions,
    clicks, purchases, revenue) and the number of distinct days it has
    data for, straight from data/<client>/meta_ads.csv. Never assumes a
    fixed number of history days: counted directly from this creative's
    own rows, so it stays correct if the dataset's own span ever changes.
    Returns all zeros (never raises) if this creative has no performance
    rows at all, since a demo test must still complete safely.
    """
    meta = load_meta_ads(client_id)
    scoped = meta[meta["creative_id"] == creative_id]
    if scoped.empty:
        return {"spend": 0.0, "impressions": 0, "clicks": 0, "purchases": 0, "revenue": 0.0, "days": 0}
    agg = aggregate_performance(scoped, by=["creative_id"]).iloc[0]
    return {
        "spend": float(agg["spend"]),
        "impressions": int(agg["impressions"]),
        "clicks": int(agg["clicks"]),
        "purchases": int(agg["purchases"]),
        "revenue": float(agg["revenue"]),
        "days": int(scoped["date"].nunique()),
    }


def _test_spend(real: dict) -> float:
    """This creative's own real daily spend rate, projected over
    DEMO_TEST_DAYS: a fair, comparable test budget derived from its own
    real run-rate, not an arbitrary number. Falls back to the full
    historical spend (better than a $0 test) if a daily rate can't be
    computed (zero recorded days).
    """
    if real["days"] <= 0 or real["spend"] <= 0:
        return round(real["spend"], 2)
    daily_spend = real["spend"] / real["days"]
    return round(daily_spend * DEMO_TEST_DAYS, 2)


def _test_impressions(real: dict, test_spend: float) -> int:
    """The SAME impressions figure for every creative in one experiment
    (current ad and every new creative alike): each gets the same test
    spend, and this holds media exposure/efficiency constant across
    variants so the simulation isolates creative-level differences
    (CTR, conversion) rather than also inventing different media-buying
    efficiency per creative. Derived from the control's own real
    impressions-per-dollar rate, never an independent guess.
    """
    if real["spend"] <= 0:
        return 0
    return max(0, round(real["impressions"] / real["spend"] * test_spend))


def _build_result(creative_id: str, role: str, name: str, image_path, spend, impressions, clicks, purchases, revenue) -> CreativeResult:
    """Rounds spend/revenue to display precision FIRST, then derives
    ctr/cpa/roas from those SAME rounded values (not the raw floats passed
    in): otherwise the stored rate could drift, by a tiny but real amount,
    from what re-dividing the stored spend/revenue/counts on this exact
    object would produce, breaking the "never independently fabricate a
    rate that contradicts the underlying counts" rule this module exists
    to enforce.
    """
    spend = round(spend, 2)
    revenue = round(revenue, 2)
    impressions = int(impressions)
    clicks = int(clicks)
    purchases = int(purchases)
    return CreativeResult(
        creative_id=creative_id,
        role=role,
        name=name,
        image_path=image_path,
        spend=spend,
        impressions=impressions,
        clicks=clicks,
        purchases=purchases,
        revenue=revenue,
        ctr=_safe_ratio(clicks, impressions),
        cpa=_safe_ratio(spend, purchases),
        roas=_safe_ratio(revenue, spend),
    )


def _current_ad_result(control_creative_id: str, image_path, real: dict, test_spend: float) -> CreativeResult:
    """The current ad's test-period result: every real count rescaled by
    the same factor (test_spend / real historical spend), so its real
    rates (ctr/cpa/roas) come through EXACTLY unchanged (scaling a
    numerator and denominator by the same factor never changes their
    ratio) at a volume that's actually comparable to a new creative with
    no history of its own. Never a randomly redrawn baseline.
    """
    if real["spend"] <= 0:
        return _build_result(control_creative_id, "current", "Current ad", image_path, test_spend, 0, 0, 0, 0.0)
    factor = test_spend / real["spend"]
    return _build_result(
        control_creative_id,
        "current",
        "Current ad",
        image_path,
        test_spend,
        max(0, round(real["impressions"] * factor)),
        max(0, round(real["clicks"] * factor)),
        max(0, round(real["purchases"] * factor)),
        max(0.0, real["revenue"] * factor),
    )


def _evidence_tilt(client_id: str, control_creative_id: str) -> float:
    """EVIDENCE_TILT if real, sufficient message-style evidence
    (core.analytics.attribute_style_leaders, the same volume/gap floors
    Marketing Intelligence itself requires) shows "customer_language"
    messaging leading for this control's own product and funnel stage;
    1.0 (no tilt) otherwise, including when the control creative can't be
    found at all. Looked up from the catalog directly, never by
    re-deriving a proposal, so this module has no dependency on agents/
    (core/ must never import agents/).
    """
    catalog = load_creative_catalog(client_id)
    row = catalog.loc[catalog["creative_id"] == control_creative_id]
    if row.empty:
        return 1.0
    product = row.iloc[0]["product_name"]
    funnel_stage = row.iloc[0]["funnel_stage"]

    joined = load_performance_with_creatives(client_id)
    leaders = attribute_style_leaders(
        joined,
        "message_style",
        products=[product],
        min_spend=PERFORMANCE_MIN_SPEND,
        min_purchases=PERFORMANCE_MIN_PURCHASES,
        min_relative_gap=PERFORMANCE_MIN_RELATIVE_GAP,
    )
    for leader in leaders:
        if leader["funnel_stage"] == funnel_stage and str(leader["leader_value"]) == "customer_language":
            return EVIDENCE_TILT
    return 1.0


def _simulate_new_creative_result(real: dict, test_spend: float, tilt: float, creative: dict, index: int) -> CreativeResult:
    """One new creative's fully synthetic test-period result: the
    control's own real CTR/conversion-rate/AOV signature, each perturbed
    by its own deterministic, independently-seeded multiplier (seeded
    from this creative's own generated_id, so the same creative always
    gets the same simulated outcome), then scaled by the shared,
    evidence-gated group tilt. Counts are computed first; ctr/cpa/roas
    are derived from them afterward (see this module's own docstring),
    so a rate can never disagree with its own counts.
    """
    generated_id = creative["generated_id"]
    control_ctr = _safe_ratio(real["clicks"], real["impressions"]) or 0.0
    control_cvr = _safe_ratio(real["purchases"], real["clicks"]) or 0.0
    control_aov = _safe_ratio(real["revenue"], real["purchases"]) or 0.0

    ctr_multiplier = _deterministic_uniform(f"{generated_id}::ctr", *CTR_MULTIPLIER_RANGE) * tilt
    cvr_multiplier = _deterministic_uniform(f"{generated_id}::cvr", *CVR_MULTIPLIER_RANGE) * tilt

    impressions = _test_impressions(real, test_spend)
    simulated_ctr = max(0.0, control_ctr * ctr_multiplier)
    clicks = max(0, round(impressions * simulated_ctr))
    simulated_cvr = max(0.0, control_cvr * cvr_multiplier)
    purchases = max(0, round(clicks * simulated_cvr))
    revenue = purchases * control_aov

    # Milestone 17C.2: use the creative's own concept_name (e.g. "Lifestyle,"
    # "Sensory focus," set once by agents/creative_studio/engine.py's fixed
    # visual-direction strategies) as the display name where the handoff
    # carries one, rather than an anonymous "Creative N": this is existing
    # CreativeVersion metadata, never a newly invented classification.
    # generated_id itself stays the object's own creative_id (backend
    # traceability), unaffected by which name is shown.
    display_name = creative.get("concept_name") or f"Creative {index + 1}"
    return _build_result(
        generated_id, "new", display_name, creative.get("image_path"),
        test_spend, impressions, clicks, purchases, revenue,
    )


def build_experiment_result(client_id: str, handoff: dict) -> ExperimentResult:
    """The one entry point: turns a prepared experiment_handoff into a
    complete, deterministic ExperimentResult. Called exactly once, from
    the "Run Demo Test" button handler in app_pages/experiments.py; the
    caller is responsible for storing the returned object (e.g. in
    st.session_state) rather than calling this again on every rerender,
    since nothing here is cached internally.

    Never calls an LLM, the image provider, or any paid API; every value
    traces to data/<client_id>/meta_ads.csv (real historical performance),
    data/<client_id>/creative_catalog.csv (product/funnel stage lookup for
    the evidence check), and the handoff's own already-approved copy/
    creative fields. Given the same handoff contents, always returns the
    exact same numbers.
    """
    control_ad = handoff["control_ad_package"]
    treatment_ad = handoff["treatment_ad_package"]
    control_creative_id = control_ad["source_creative_id"]

    real = _real_creative_aggregate(client_id, control_creative_id)
    test_spend = _test_spend(real)
    tilt = _evidence_tilt(client_id, control_creative_id)

    current_result = _current_ad_result(control_creative_id, control_ad.get("source_image_path"), real, test_spend)
    treatment_results = [
        _simulate_new_creative_result(real, test_spend, tilt, creative, index)
        for index, creative in enumerate(treatment_ad["selected_creative_versions"])
    ]

    return ExperimentResult(
        experiment_id=handoff["proposal_id"],
        client_id=client_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        current_ad_result=current_result,
        treatment_results=treatment_results,
    )


def build_concept_arms_result(client_id: str, handoff: dict) -> ExperimentResult:
    """Milestone 23 (Experiments V2): the entry point for a Creative Lab V2
    handoff, whose "new creatives" are several Creative Concepts designed
    to answer one learning question (e.g. "which messaging angle deserves
    further investment"), not a current-ad-vs-treatments comparison. Every
    selected concept becomes its own experiment ARM in treatment_results;
    current_ad_result is explicitly None, since an existing Brio ad is
    never automatically one of the experimental arms in this experiment
    type (see this module's and agents/performance/engine.py's own
    docstrings). Reuses every piece of the existing simulation math
    UNCHANGED (_real_creative_aggregate, _test_spend, _evidence_tilt,
    _simulate_new_creative_result): only which result gets returned as
    "current" differs.

    The handoff's own control_ad_package.source_creative_id (an existing,
    same-product/same-funnel-stage ad Creative Lab already selected
    deterministically) is reused here ONLY as a REFERENCE anchor: its real
    historical CTR/conversion-rate/AOV signature and real daily spend rate
    set a realistic, comparable per-arm test budget and base rates, the
    same "don't invent a number from nothing" discipline
    build_experiment_result already follows. That ad is never exposed in
    the returned result as a competing arm, and is never labeled a
    "control" or "winner" anywhere downstream; it is creative memory and a
    performance reference, nothing more.

    Every arm gets the SAME test_spend and the SAME evidence-gated tilt
    (comparable test budgets/delivery assumptions across arms, per this
    milestone's own explicit instruction), then its own independent,
    deterministic, hash-seeded variation, so no arm is guaranteed to lead
    and a real spread (including a genuinely close result) stays possible.
    """
    reference_ad = handoff["control_ad_package"]
    reference_creative_id = reference_ad["source_creative_id"]

    real = _real_creative_aggregate(client_id, reference_creative_id)
    test_spend = _test_spend(real)
    tilt = _evidence_tilt(client_id, reference_creative_id)

    arm_results = [
        _simulate_new_creative_result(real, test_spend, tilt, arm, index)
        for index, arm in enumerate(handoff["treatment_ad_package"]["selected_creative_versions"])
    ]

    return ExperimentResult(
        experiment_id=handoff["proposal_id"],
        client_id=client_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        current_ad_result=None,
        treatment_results=arm_results,
    )
