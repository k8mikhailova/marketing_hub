"""Performance Agent: deterministic preview implementation of experiment
analysis (Milestone 17B). Turns one already-computed
core.experiment_simulation.ExperimentResult, plus the experiment_handoff
it belongs to, into a structured ExperimentAnalysis: a careful,
evidence-grounded interpretation, never a blind "highest ROAS wins."

Exactly like agents/intelligence/engine.py, agents/strategist/engine.py,
and agents/creative_studio/engine.py, this is the "preview" implementation
described in the README: fixed, deterministic rules that produce the same
structured output a future live model call would return.
`generated_by=GENERATED_BY_PREVIEW` marks it as such.

Python-owns-facts boundary: every number here (deltas, purchase counts,
evidence tier) is arithmetic over ExperimentResult's own already-validated
counts and rates. This module never recomputes ROAS/CTR/CPA from scratch,
never calls an LLM, and never invents a number; it only classifies and
narrates numbers that already exist. The narration templates are plain
string formatting over those numbers, not natural-language generation,
matching the same "AI owns interpretation, Python owns facts" split every
other agent's preview implementation already follows.

Central discipline this module exists to enforce (see the milestone's own
brief): never claim statistical significance this demo can't support,
never claim causality, and never let a "highest ROAS creative" default
into "winner." A per-creative outcome, an overall hypothesis assessment,
and a separate evidence-strength tier all stay independent fields, on
purpose: a promising-looking delta on a tiny sample must read as
"insufficient_evidence," not as "supported," and a batch where one
creative clearly wins while another clearly loses must read as "mixed,"
not as a verdict on the hypothesis either way. The assessment vocabulary
itself is capped at "supported_directionally" (never "proven" or
"confirmed") regardless of how much volume backs it: this demo's
synthetic experiment, even at its best, only ever supports a direction,
never a certainty.

Traceability: analyze_experiment reads client_id/experiment_id straight
from the ExperimentResult, and hypothesis/source_finding_id from the
handoff dict Creative Lab already built (agents.creative_studio has no
schema change here; this module only reads that same dict), so an
analysis can always be traced back to Customer Signal -> Finding ->
ExperimentProposal -> AdPackage -> selected creatives -> this result,
without inventing a parallel state store.
"""
from dataclasses import dataclass, field

from agents.intelligence.engine import GENERATED_BY_PREVIEW
from core.analytics import PERFORMANCE_MIN_PURCHASES, PERFORMANCE_MIN_RELATIVE_GAP
from core.experiment_simulation import CreativeResult, ExperimentResult

# The lower purchase-count floor for this analysis' own 3-tier evidence
# scale (below core.analytics.PERFORMANCE_MIN_PURCHASES, the app's
# existing "trust this comparison at all" floor, reused here as the
# "strong" tier's own threshold for consistency with the rest of the
# app). An isolated demo-legibility choice, like this project's other
# threshold constants, not a statistical claim.
EVIDENCE_WEAK_PURCHASES_FLOOR = 5

OUTCOME_IMPROVED = "improved"
OUTCOME_UNDERPERFORMED = "underperformed"
OUTCOME_MIXED = "mixed"
OUTCOME_NEUTRAL = "neutral"

ASSESSMENT_SUPPORTED_DIRECTIONALLY = "supported_directionally"
ASSESSMENT_MIXED = "mixed"
ASSESSMENT_NOT_SUPPORTED = "not_supported"
ASSESSMENT_INSUFFICIENT_EVIDENCE = "insufficient_evidence"

EVIDENCE_WEAK = "weak"
EVIDENCE_MODERATE = "moderate"
EVIDENCE_STRONG = "strong"

NEXT_STEP_TEST_AGAIN = "test_again"
NEXT_STEP_SCALE_CAUTIOUSLY = "scale_cautiously"
NEXT_STEP_ITERATE_CREATIVE = "iterate_creative"
NEXT_STEP_RETURN_TO_CURRENT = "return_to_current"
NEXT_STEP_NEEDS_MORE_DATA = "needs_more_data"

# Human-facing labels for the two enums above, kept next to their own
# constants so any caller (today, a temporary inspection block in
# app_pages/experiments.py; later, the real results UI) shows the same
# wording rather than each re-deriving its own from the raw enum value.
ASSESSMENT_LABELS = {
    ASSESSMENT_SUPPORTED_DIRECTIONALLY: "Directional support",
    ASSESSMENT_MIXED: "Mixed",
    ASSESSMENT_NOT_SUPPORTED: "Not supported",
    ASSESSMENT_INSUFFICIENT_EVIDENCE: "Insufficient evidence",
}

# Milestone 17C.1: action-oriented phrasing (a verb a marketer would say
# out loud), not a status label, since these render right next to the
# human-decision buttons on the results page and should read like the
# same kind of sentence. The backend enum values themselves are
# unchanged, since existing logic and tests key off them.
NEXT_STEP_LABELS = {
    NEXT_STEP_TEST_AGAIN: "Run another test",
    NEXT_STEP_SCALE_CAUTIOUSLY: "Continue testing cautiously",
    NEXT_STEP_ITERATE_CREATIVE: "Try another creative direction",
    NEXT_STEP_RETURN_TO_CURRENT: "Keep current ad",
    NEXT_STEP_NEEDS_MORE_DATA: "Collect more data",
}

# Milestone 17C: deliberately conservative display wording for the
# evidence-strength tier. The backend tier names (weak/moderate/strong)
# stay as they were, since existing logic and tests key off them, but
# "strong" was found, on UI review, to read as a claim of statistical
# confidence it doesn't earn just because purchase count crossed
# PERFORMANCE_MIN_PURCHASES; nothing about this demo's synthetic
# experiment ever supports more than a directional read, so even its best
# tier is labeled "Moderate," never "Strong" or "Confirmed."
EVIDENCE_STRENGTH_LABELS = {
    EVIDENCE_WEAK: "Limited",
    EVIDENCE_MODERATE: "Directional",
    EVIDENCE_STRONG: "Moderate",
}

# User-friendly display labels for a per-creative outcome, distinct from
# the assessment labels above (which describe the WHOLE experiment): a
# card shows this instead of the raw enum, right under its own metrics.
OUTCOME_LABELS = {
    OUTCOME_IMPROVED: "Promising",
    OUTCOME_UNDERPERFORMED: "Underperformed",
    OUTCOME_MIXED: "Mixed",
    OUTCOME_NEUTRAL: "Similar",
}


@dataclass
class CreativeAnalysis:
    """One new creative's comparison against the current ad: the
    quantitative deltas ALWAYS survive alongside the categorical outcome
    and its one-sentence interpretation, so a caller (a future UI, a
    saved-learning step, a test) never has to re-derive a number that was
    already computed here. A delta is None only when it's genuinely
    undefined (a zero baseline), never a fabricated 0.0.
    """

    creative_id: str
    name: str
    roas_delta_pct: float | None
    ctr_delta_pct: float | None
    cpa_delta_pct: float | None
    purchases_delta: int
    purchases_delta_pct: float | None
    outcome: str  # "improved" | "underperformed" | "mixed" | "neutral"
    interpretation: str


@dataclass
class ExperimentAnalysis:
    """The Performance Agent's structured output for one experiment:
    facts (current_ad_summary, creative_analyses, each already a typed,
    quantitative object) plus this module's own deterministic
    interpretation (hypothesis_assessment, evidence_strength, summary,
    key_observations, recommended_next_step). Never written to
    clients/<client>/approved_learnings.json by this module: that's a
    future, human-approved step, not something an analysis does to
    itself.

    Milestone 17C.2 added headline_creative_id/headline/ai_findings/
    recommendation_note for the redesigned results page (a "results hero"
    the user can read without scrolling, and a synthesized "What the AI
    found" list, replacing the earlier per-card-only presentation); the
    original summary/key_observations/evidence_strength/
    recommended_next_step fields are UNCHANGED and still computed exactly
    as before, since existing logic and tests key off them.
    """

    experiment_id: str
    client_id: str
    source_finding_id: str
    hypothesis: str
    primary_metric: str
    current_ad_summary: CreativeResult
    creative_analyses: list[CreativeAnalysis] = field(default_factory=list)
    best_observed_creative_id: str | None = None
    hypothesis_assessment: str = ASSESSMENT_INSUFFICIENT_EVIDENCE
    evidence_strength: str = EVIDENCE_WEAK
    evidence_strength_reason: str = ""
    summary: str = ""
    key_observations: list[str] = field(default_factory=list)
    recommended_next_step: str = NEXT_STEP_NEEDS_MORE_DATA
    headline_creative_id: str | None = None
    headline: str = ""
    ai_findings: list[str] = field(default_factory=list)
    recommendation_note: str = ""
    data_type: str = "demo_synthetic"
    generated_by: str = GENERATED_BY_PREVIEW


def _relative_delta(new: float | None, old: float | None) -> float | None:
    """(new - old) / old, or None when old is zero/undefined: "no
    baseline" is a real, distinct fact, never reported as a fabricated
    0% or 100% change.
    """
    if not old or new is None:
        return None
    return (new - old) / old


def _direction(new: float | None, old: float | None, gap: float = PERFORMANCE_MIN_RELATIVE_GAP) -> str:
    """"up" / "down" / "flat" from two raw values, using the app's own
    existing non-noise gap (core.analytics.PERFORMANCE_MIN_RELATIVE_GAP,
    the same floor message_style_leaders and attribute_style_leaders
    already require) so a small, plausibly-noise move never gets called a
    real improvement or decline. A zero/undefined baseline is handled
    honestly for DIRECTION purposes only (old == 0 and new > 0 is an
    unambiguous "up," even though "percent change from zero" isn't a
    number worth reporting); the separately-stored delta fields always
    use _relative_delta instead, which returns None in that same case
    rather than inventing a percentage.
    """
    if not old:
        return "up" if new and new > 0 else "flat"
    if new is None:
        return "flat"
    delta = (new - old) / old
    if delta >= gap:
        return "up"
    if delta <= -gap:
        return "down"
    return "flat"


def _direction_from_delta(delta: float | None, gap: float = PERFORMANCE_MIN_RELATIVE_GAP) -> str:
    """"up" / "down" / "flat" from an already-computed relative delta
    (as opposed to _direction, which works from two raw values and
    special-cases a zero baseline): used where a delta was already
    computed and stored (e.g. on a CreativeAnalysis) and re-deriving it
    from raw values again would be redundant.
    """
    if delta is None:
        return "flat"
    if delta >= gap:
        return "up"
    if delta <= -gap:
        return "down"
    return "flat"


def _cpa_conflict_note(ca: CreativeAnalysis) -> str | None:
    """A small, explicit review this milestone asked for: CPA and
    purchases inform the narrative but don't drive _classify_outcome
    (ROAS+CTR do), so a material disagreement between CPA and ROAS could
    otherwise stay hidden. A genuine conflict is CPA getting WORSE
    (higher cost) while ROAS improves, or CPA getting BETTER (lower cost)
    while ROAS declines, each by a real, non-noise margin; note that this
    demo's own simulation (core/experiment_simulation.py) holds spend and
    each creative's own AOV constant, so in practice CPA and ROAS move
    together (not in conflict) far more often than not with today's data,
    a real, disclosed limitation of the simulation, not of this check:
    the check itself stays general and would catch a genuine disagreement
    if the underlying data ever produced one (e.g. real performance data,
    or a future simulation with per-creative AOV).
    """
    if ca.cpa_delta_pct is None or ca.roas_delta_pct is None:
        return None
    roas_dir = _direction_from_delta(ca.roas_delta_pct)
    cpa_dir = _direction_from_delta(ca.cpa_delta_pct)  # "up" = cost rose = worse
    if roas_dir == "up" and cpa_dir == "up":
        return f"{ca.name} improved ROAS, but its CPA also rose {_format_pct(ca.cpa_delta_pct)} versus the current ad, worth watching."
    if roas_dir == "down" and cpa_dir == "down":
        return f"{ca.name} underperformed on ROAS, but its CPA fell {_format_pct(ca.cpa_delta_pct)} versus the current ad, worth watching."
    return None


def _classify_outcome(current: CreativeResult, creative: CreativeResult) -> str:
    """The per-creative outcome, decided on ROAS (this experiment's own
    stated primary measure) and CTR (the metric most directly attributable
    to a creative's own execution, as opposed to CPA/purchases, which also
    absorb this demo's simulated conversion-rate noise). Deliberately NOT
    a single combined score: when ROAS and CTR point in different
    directions, that disagreement IS the finding ("mixed"), not something
    to average away. CPA and purchases stay fully available on
    CreativeAnalysis for context, just not as inputs to this
    classification.
    """
    roas_dir = _direction(creative.roas, current.roas)
    ctr_dir = _direction(creative.ctr, current.ctr)

    if {roas_dir, ctr_dir} == {"up", "down"}:
        return OUTCOME_MIXED
    if roas_dir == "up":
        return OUTCOME_IMPROVED
    if roas_dir == "down":
        return OUTCOME_UNDERPERFORMED
    return OUTCOME_NEUTRAL


def _format_pct(value: float | None) -> str:
    return f"{value:+.0%}" if value is not None else "an undefined change (no comparable baseline)"


def _creative_interpretation(name: str, outcome: str, roas_delta: float | None, ctr_delta: float | None) -> str:
    roas_txt = f"{_format_pct(roas_delta)} ROAS" if roas_delta is not None else "ROAS with no comparable baseline"
    ctr_txt = f"{_format_pct(ctr_delta)} CTR" if ctr_delta is not None else "CTR with no comparable baseline"
    if outcome == OUTCOME_IMPROVED:
        return f"{name} improved on the current ad ({roas_txt}, {ctr_txt})."
    if outcome == OUTCOME_UNDERPERFORMED:
        return f"{name} underperformed the current ad ({roas_txt}, {ctr_txt})."
    if outcome == OUTCOME_MIXED:
        return f"{name} showed a mixed result versus the current ad ({roas_txt}, {ctr_txt}): the two metrics moved in different directions."
    return f"{name} performed about the same as the current ad ({roas_txt}, {ctr_txt})."


def _build_creative_analysis(current: CreativeResult, creative: CreativeResult) -> CreativeAnalysis:
    roas_delta = _relative_delta(creative.roas, current.roas)
    ctr_delta = _relative_delta(creative.ctr, current.ctr)
    cpa_delta = _relative_delta(creative.cpa, current.cpa)
    purchases_delta = creative.purchases - current.purchases
    purchases_delta_pct = _relative_delta(creative.purchases, current.purchases)
    outcome = _classify_outcome(current, creative)

    return CreativeAnalysis(
        creative_id=creative.creative_id,
        name=creative.name,
        roas_delta_pct=roas_delta,
        ctr_delta_pct=ctr_delta,
        cpa_delta_pct=cpa_delta,
        purchases_delta=purchases_delta,
        purchases_delta_pct=purchases_delta_pct,
        outcome=outcome,
        interpretation=_creative_interpretation(creative.name, outcome, roas_delta, ctr_delta),
    )


def _min_purchases(current: CreativeResult, treatments: list[CreativeResult]) -> int:
    purchase_counts = [current.purchases] + [c.purchases for c in treatments]
    return min(purchase_counts) if purchase_counts else 0


def _evidence_strength(min_purchases: int, creative_analyses: list[CreativeAnalysis]) -> str:
    """A 3-tier evidence-strength read, deterministic, never an LLM
    guessing whether to hedge. Volume is the primary input (the weakest
    purchase count anywhere in the comparison caps how much confidence
    the WHOLE analysis can carry, since the current ad's own low volume
    is just as limiting as a treatment creative's); "consistency across
    metrics" (this milestone's own explicit requirement) is the second
    input: even a good-volume batch drops out of "strong" if any creative
    shows a genuinely mixed (ROAS/CTR disagree) result, since that
    disagreement is itself a form of noisy evidence.
    """
    if min_purchases < EVIDENCE_WEAK_PURCHASES_FLOOR:
        return EVIDENCE_WEAK
    if min_purchases < PERFORMANCE_MIN_PURCHASES:
        return EVIDENCE_MODERATE
    if any(ca.outcome == OUTCOME_MIXED for ca in creative_analyses):
        return EVIDENCE_MODERATE
    return EVIDENCE_STRONG


def _evidence_strength_reason(evidence_strength: str, min_purchases: int) -> str:
    """One sentence explaining the evidence tier from the actual purchase
    count behind it, generated from the real evidence state, never a
    hardcoded scenario. Even the best tier ("Moderate" display label,
    EVIDENCE_STRONG backend) is phrased as still-directional, never as
    statistically confirmed: this demo's synthetic experiment cannot
    support a stronger claim at any volume.

    Milestone 17C.2: deliberately uses "signal" / "pattern" / "learning"
    vocabulary (Part 5's own RESULT vs. POTENTIAL LEARNING vs. APPROVED
    LEARNING distinction) rather than more abstract words like
    "directional"/"conclusive," so the tie to what a human can and can't
    do with this result (a future Save Learning decision) is explicit,
    not just implied.
    """
    plural = "" if min_purchases == 1 else "s"
    if evidence_strength == EVIDENCE_WEAK:
        return (
            f"Purchase volume is still small ({min_purchases} purchase{plural}), so this is a promising "
            "signal rather than a reliable learning."
        )
    if evidence_strength == EVIDENCE_MODERATE:
        return (
            f"Purchase volume is moderate ({min_purchases} purchase{plural}): this reads as a potential "
            "pattern worth tracking, not yet a confirmed learning."
        )
    return (
        f"Purchase volume is the best available in this test ({min_purchases} purchase{plural}), though "
        "still a directional pattern, not a statistically confirmed learning."
    )


def _hypothesis_assessment(evidence_strength: str, outcomes: list[str]) -> str:
    """Rule-grounded, never a simple pass/fail. "weak" evidence always
    wins the vote regardless of how the numbers look (a striking-looking
    delta on a tiny sample is still insufficient evidence, not a result);
    otherwise the assessment reads the SET of per-creative outcomes, never
    an average: any disagreement between an improved and an underperformed
    (or any creative individually flagged "mixed") makes the whole
    experiment "mixed," since execution-sensitivity is itself the finding,
    not something to net out. The vocabulary is deliberately capped at
    "supported_directionally," never "proven"/"confirmed"/"significant,"
    regardless of evidence_strength: this demo experiment cannot support a
    stronger claim than direction, no matter how much volume backs it.
    """
    if evidence_strength == EVIDENCE_WEAK or not outcomes:
        return ASSESSMENT_INSUFFICIENT_EVIDENCE

    outcome_set = set(outcomes)
    if OUTCOME_MIXED in outcome_set or (OUTCOME_IMPROVED in outcome_set and OUTCOME_UNDERPERFORMED in outcome_set):
        return ASSESSMENT_MIXED
    if OUTCOME_IMPROVED in outcome_set:
        return ASSESSMENT_SUPPORTED_DIRECTIONALLY
    return ASSESSMENT_NOT_SUPPORTED  # every outcome is "underperformed" and/or "neutral"


def _recommended_next_step(assessment: str, evidence_strength: str) -> str:
    """A bounded advisory category for a human marketer, never an
    autonomous action: this module never touches Meta, never writes a
    learning, and never decides anything on its own. "strong" evidence is
    the only thing that can push a next step past the cautious middle
    ground (test_again / needs_more_data); a not_supported read still
    recommends more data, not an outright return, unless the evidence is
    actually strong enough to trust that read.
    """
    if assessment == ASSESSMENT_INSUFFICIENT_EVIDENCE:
        return NEXT_STEP_NEEDS_MORE_DATA
    if assessment == ASSESSMENT_MIXED:
        return NEXT_STEP_ITERATE_CREATIVE
    if assessment == ASSESSMENT_SUPPORTED_DIRECTIONALLY:
        return NEXT_STEP_SCALE_CAUTIOUSLY if evidence_strength == EVIDENCE_STRONG else NEXT_STEP_TEST_AGAIN
    if assessment == ASSESSMENT_NOT_SUPPORTED:
        return NEXT_STEP_RETURN_TO_CURRENT if evidence_strength == EVIDENCE_STRONG else NEXT_STEP_NEEDS_MORE_DATA
    return NEXT_STEP_NEEDS_MORE_DATA


def _best_observed_creative_id(treatments: list[CreativeResult], evidence_strength: str) -> str | None:
    """The highest-ROAS new creative, purely as an observed fact for
    traceability, only surfaced once evidence clears the "weak" floor
    (with too little data, even naming an "observed best" overstates what
    the test showed). Never labeled or treated as a "winner": nothing
    downstream (assessment, recommendation) is derived from this field,
    and callers are expected to keep it framed as observation, not
    verdict, per this milestone's own explicit instruction.
    """
    if not treatments or evidence_strength == EVIDENCE_WEAK:
        return None
    return max(treatments, key=lambda c: c.roas or 0.0).creative_id


def _strongest_observed(treatments: list[CreativeResult]) -> CreativeResult | None:
    """The highest-ROAS new creative, regardless of evidence_strength:
    deliberately DIFFERENT from _best_observed_creative_id, which stays
    None under weak evidence for a downstream-traceability reason. This
    one purely names which creative the results page's hero section
    should headline (Milestone 17C.2's own explicit brief: the hero must
    show a concrete result even under "Limited" evidence, paired with the
    evidence caveat right next to it, never presented as a decided
    winner). Never used to drive hypothesis_assessment or evidence_
    strength themselves.
    """
    if not treatments:
        return None
    return max(treatments, key=lambda c: c.roas or 0.0)


def _join_and(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _headline(headline_creative: CreativeResult | None, headline_ca: CreativeAnalysis | None) -> str:
    """The ONE sentence the results page's hero renders without scrolling
    (Milestone 17C.2, Part 1): names the highest-ROAS new creative and
    what happened to it, phrased by its own outcome so an all-underperform
    batch never gets framed as though something "won." Never claims
    statistical significance; the evidence caveat is a SEPARATE sentence
    (evidence_strength_reason), not folded in here, so this stays purely
    about what was observed.
    """
    if headline_creative is None or headline_ca is None:
        return "No comparable result yet."
    name = headline_creative.name
    if headline_ca.outcome == OUTCOME_IMPROVED:
        return f"{name} showed the strongest result in this test."
    if headline_ca.outcome == OUTCOME_UNDERPERFORMED:
        return f"{name} came closest to the current ad, but still underperformed it."
    if headline_ca.outcome == OUTCOME_MIXED:
        return f"{name} had the strongest ROAS in this test, though its results were mixed."
    return f"{name} performed about the same as the current ad."


def _recommendation_note(headline_creative: CreativeResult | None, headline_ca: CreativeAnalysis | None, evidence_strength: str) -> str:
    """One sentence connecting the headline creative to what a human can
    actually do next (Milestone 17C.2, Part 6): explicitly distinguishes a
    RESULT ("X produced ROAS Y") from something worth saving as a learning,
    per this milestone's own RESULT/POTENTIAL LEARNING/APPROVED LEARNING
    architecture (see this module's docstring and Part 5 of the brief).
    "Weak" evidence never implies a learning is ready to save, regardless
    of how promising the headline creative looks.
    """
    if headline_creative is None or headline_ca is None:
        return "There isn't enough of a result yet to recommend a next step."
    name = headline_creative.name
    if evidence_strength == EVIDENCE_WEAK:
        # Deliberately does not repeat the "purchase volume" phrase already
        # stated once in the hero's own evidence_strength_reason
        # (Milestone 17C.1's own lesson: the same caveat showing up twice
        # on one page reads as repetitive).
        return f"{name} is promising, but there isn't enough evidence yet to save this as an approved learning."
    if headline_ca.outcome == OUTCOME_IMPROVED:
        return f"{name} improved on the current ad with evidence strong enough to consider saving this as a learning."
    if headline_ca.outcome == OUTCOME_UNDERPERFORMED:
        return f"{name} underperformed the current ad; keeping the current ad may be better than saving this as a learning."
    return f"{name} showed a mixed result against the current ad; another test would help before saving this as a learning."


def _cross_creative_pattern(
    strongest: CreativeResult, strongest_meta: dict | None, weakest: CreativeResult, weakest_meta: dict | None
) -> str | None:
    """A cross-creative finding connecting performance back to a creative
    decision actually tested (Milestone 17C.2, Part 4), using ONLY fields
    that already exist on CreativeVersion and already reached this module
    via the handoff (concept_name, on_image_proof): never a new
    classification invented from free text. Returns None (never a forced,
    unsupported comparison) whenever metadata for either creative is
    missing, or when the two don't actually differ on either dimension:
    per the brief, "if the available metadata cannot support a
    cross-creative pattern, omit it." Deliberately associative language
    ("this may suggest," "is consistent with"), never causal.
    """
    if not strongest_meta or not weakest_meta or strongest.creative_id == weakest.creative_id:
        return None
    strongest_proof = bool(strongest_meta.get("on_image_proof"))
    weakest_proof = bool(weakest_meta.get("on_image_proof"))
    strongest_name = strongest_meta.get("concept_name")
    weakest_name = weakest_meta.get("concept_name")

    if strongest_proof != weakest_proof and strongest_name and weakest_name:
        with_proof = strongest_name if strongest_proof else weakest_name
        without_proof = weakest_name if strongest_proof else strongest_name
        return (
            f"In this test, {with_proof} (with an in-image proof claim) and {without_proof} (without one) "
            "performed differently; this may suggest proof visibility is worth testing further, though a "
            "single comparison isn't enough to confirm it."
        )
    if strongest_name and weakest_name and strongest_name != weakest_name:
        return (
            f"The stronger execution used the {strongest_name} direction, while the weaker one used "
            f"{weakest_name}; this pattern is consistent with execution mattering here, though it's based "
            "on a small comparison and isn't yet a confirmed pattern."
        )
    return None


def _build_ai_findings(
    treatments: list[CreativeResult],
    creative_analyses: list[CreativeAnalysis],
    creative_metadata: list[dict],
) -> list[str]:
    """2-4 compact findings synthesizing the experiment (Milestone 17C.2,
    Part 4), replacing the earlier generic "What we learned" text block.
    Reuses the SAME per-creative outcome classification _classify_outcome
    already computed (never a new signal): groups by outcome, names which
    creative(s) improved/underperformed/were mixed, adds any genuine
    CPA-vs-ROAS conflict (_cpa_conflict_note, unchanged from Milestone
    17C), and a cross-creative metadata pattern when the data actually
    supports one. Deliberately never states the purchase-volume/evidence
    caveat here: that's the results hero's own job
    (evidence_strength_reason), stated exactly once on the page.
    """
    if not treatments:
        return []
    findings: list[str] = []

    improved = [(t, ca) for t, ca in zip(treatments, creative_analyses) if ca.outcome == OUTCOME_IMPROVED]
    underperformed = [(t, ca) for t, ca in zip(treatments, creative_analyses) if ca.outcome == OUTCOME_UNDERPERFORMED]
    mixed = [(t, ca) for t, ca in zip(treatments, creative_analyses) if ca.outcome == OUTCOME_MIXED]

    if improved:
        best_t, best_ca = max(improved, key=lambda pair: pair[1].roas_delta_pct or 0.0)
        ctr_clause = f" and CTR by {_format_pct(best_ca.ctr_delta_pct)}" if best_ca.ctr_delta_pct is not None else ""
        findings.append(f"{best_t.name} showed the strongest result, improving ROAS by {_format_pct(best_ca.roas_delta_pct)}{ctr_clause} versus the current ad.")
    if underperformed:
        names = _join_and([t.name for t, _ in underperformed])
        deltas = [ca.roas_delta_pct for _, ca in underperformed if ca.roas_delta_pct is not None]
        worst_clause = f", down as much as {_format_pct(min(deltas))}" if deltas else ""
        findings.append(f"{names} underperformed the current ad on ROAS{worst_clause}.")
    if mixed:
        names = _join_and([t.name for t, _ in mixed])
        findings.append(f"{names} showed a mixed result: ROAS and CTR moved in different directions versus the current ad.")
    if not improved and not underperformed and not mixed:
        findings.append("All new creatives performed about the same as the current ad in this test.")

    conflict_notes = [note for note in (_cpa_conflict_note(ca) for ca in creative_analyses) if note]
    findings.extend(conflict_notes[: max(0, 4 - len(findings))])

    if len(treatments) > 1 and len(findings) < 4:
        meta_by_id = {m.get("generated_id"): m for m in creative_metadata if m.get("generated_id")}
        strongest = max(treatments, key=lambda c: c.roas or 0.0)
        weakest = min(treatments, key=lambda c: c.roas or 0.0)
        pattern = _cross_creative_pattern(strongest, meta_by_id.get(strongest.creative_id), weakest, meta_by_id.get(weakest.creative_id))
        if pattern:
            findings.append(pattern)

    return findings[:4]


def _summary(assessment: str, evidence_strength: str, creative_analyses: list[CreativeAnalysis]) -> str:
    """One interpretation sentence describing WHAT happened, deliberately
    never restating the purchase-volume/evidence-tier caveat (Milestone
    17C.1): that's evidence_strength_reason's exclusive job, and the
    results page renders the two together as one paragraph, so repeating
    it here would make the same caveat appear twice on screen. evidence_
    strength is still accepted (kept for a stable call signature and
    because a future caller may want it) but no longer interpolated into
    the sentence itself.
    """
    n = len(creative_analyses)
    n_improved = sum(1 for c in creative_analyses if c.outcome == OUTCOME_IMPROVED)
    n_under = sum(1 for c in creative_analyses if c.outcome == OUTCOME_UNDERPERFORMED)
    n_mixed = sum(1 for c in creative_analyses if c.outcome == OUTCOME_MIXED)

    if assessment == ASSESSMENT_INSUFFICIENT_EVIDENCE:
        if n_improved and not n_under and not n_mixed:
            lead = creative_analyses[0].name if n == 1 else f"{n_improved} of {n} new creatives"
            return f"{lead} looked promising on ROAS in this test, but there isn't enough data yet to treat that as a result."
        if n_under and not n_improved and not n_mixed:
            lead = creative_analyses[0].name if n == 1 else f"{n_under} of {n} new creatives"
            return f"{lead} looked weaker on ROAS in this test, but there isn't enough data yet to treat that as a result."
        return "The pattern in this test is too thin to characterize with any confidence yet."
    if assessment == ASSESSMENT_SUPPORTED_DIRECTIONALLY:
        lead = creative_analyses[0].name if n == 1 else f"{n_improved} of {n} new creatives"
        return f"{lead} improved on the current ad, giving directional support to the hypothesis."
    if assessment == ASSESSMENT_NOT_SUPPORTED:
        return f"The new creative{'s' if n != 1 else ''} did not outperform the current ad; the hypothesis is not supported by this test."

    mixed_clause = f", and {n_mixed} showed ROAS and CTR moving in different directions" if n_mixed else ""
    return (
        f"Results were mixed across executions: {n_improved} improved and {n_under} underperformed{mixed_clause}. "
        "This suggests the messaging direction may be promising, but the result is sensitive to execution."
    )


def _key_observations(treatments: list[CreativeResult], creative_analyses: list[CreativeAnalysis]) -> list[str]:
    """1-2 concise, deterministic, genuinely useful observations built from
    the actual numbers, never a hardcoded sentence for a specific
    scenario: the same templates apply whether this experiment has 1 or 6
    new creatives. Deliberately does NOT restate the purchase-volume/
    evidence-tier caveat (Milestone 17C.1): that caveat is stated exactly
    once, via evidence_strength_reason, so repeating it here as its own
    bullet would make the same sentence appear on screen twice. Prioritizes
    a genuine CPA-vs-ROAS conflict (see _cpa_conflict_note), since a hidden
    conflicting metric is more actionable than a restatement of who ranked
    highest.
    """
    observations: list[str] = []

    conflict_notes = [note for note in (_cpa_conflict_note(ca) for ca in creative_analyses) if note]
    observations.extend(conflict_notes)

    if len(observations) < 2:
        if len(treatments) == 1:
            observations.append(creative_analyses[0].interpretation)
        elif len(treatments) > 1:
            best = max(treatments, key=lambda c: c.roas or 0.0)
            worst = min(treatments, key=lambda c: c.roas or 0.0)
            if best.creative_id != worst.creative_id:
                observations.append(
                    f"{best.name} had the strongest ROAS ({best.roas:.2f}x) among new creatives, while "
                    f"{worst.name} had the weakest ({worst.roas:.2f}x)."
                )
            else:
                observations.append("All new creatives landed close to the same ROAS in this test.")

    if len(observations) < 2:
        mixed_names = [ca.name for ca in creative_analyses if ca.outcome == OUTCOME_MIXED]
        if mixed_names:
            observations.append(
                f"{', '.join(mixed_names)} showed ROAS and CTR moving in different directions, a sign that "
                "engagement and efficiency gains don't always move together."
            )

    return observations[:2]


def analyze_experiment(handoff: dict, result: ExperimentResult) -> ExperimentAnalysis:
    """The one entry point: turns a completed ExperimentResult, plus the
    experiment_handoff it belongs to, into a structured ExperimentAnalysis.
    Reads hypothesis/source_finding_id straight from the handoff dict
    Creative Lab already built (no new state, no re-deriving a proposal);
    every other field is arithmetic over ExperimentResult's own counts and
    rates. Called automatically as part of "Run Demo Test"
    (app_pages/experiments.py); never called on every rerender, and never
    makes an LLM, image-provider, or paid API call of any kind.

    Since Milestone 17C.2, also reads handoff["treatment_ad_package"]
    ["selected_creative_versions"] (already-existing CreativeVersion
    metadata Creative Lab attached to the handoff: concept_name,
    on_image_proof) to ground ai_findings' cross-creative-pattern finding;
    this list is aligned by POSITION with result.treatment_results, since
    core.experiment_simulation.build_experiment_result builds treatment_
    results by enumerating this exact same list in this exact same order.
    Absent or misaligned metadata (e.g. a hand-built test ExperimentResult
    with no matching handoff) degrades gracefully to no cross-creative
    finding, never a crash or a fabricated one.
    """
    current = result.current_ad_result
    treatments = result.treatment_results

    creative_analyses = [_build_creative_analysis(current, c) for c in treatments]
    min_purchases = _min_purchases(current, treatments)
    evidence_strength = _evidence_strength(min_purchases, creative_analyses)
    assessment = _hypothesis_assessment(evidence_strength, [ca.outcome for ca in creative_analyses])

    creative_metadata = handoff.get("treatment_ad_package", {}).get("selected_creative_versions", [])
    headline_creative = _strongest_observed(treatments)
    ca_by_id = {ca.creative_id: ca for ca in creative_analyses}
    headline_ca = ca_by_id.get(headline_creative.creative_id) if headline_creative else None

    return ExperimentAnalysis(
        experiment_id=result.experiment_id,
        client_id=result.client_id,
        source_finding_id=handoff.get("source_finding_id", ""),
        hypothesis=handoff.get("hypothesis", ""),
        primary_metric="ROAS",
        current_ad_summary=current,
        creative_analyses=creative_analyses,
        best_observed_creative_id=_best_observed_creative_id(treatments, evidence_strength),
        hypothesis_assessment=assessment,
        evidence_strength=evidence_strength,
        evidence_strength_reason=_evidence_strength_reason(evidence_strength, min_purchases),
        summary=_summary(assessment, evidence_strength, creative_analyses),
        key_observations=_key_observations(treatments, creative_analyses),
        recommended_next_step=_recommended_next_step(assessment, evidence_strength),
        headline_creative_id=headline_creative.creative_id if headline_creative else None,
        headline=_headline(headline_creative, headline_ca),
        ai_findings=_build_ai_findings(treatments, creative_analyses, creative_metadata),
        recommendation_note=_recommendation_note(headline_creative, headline_ca, evidence_strength),
    )


# =============================================================================
# Milestone 23 (Experiments V2): multi-arm CONCEPT experiment analysis.
# =============================================================================
# Everything above this line analyzes a current-ad-vs-treatments experiment
# and is UNCHANGED: still valid, still callable, kept for a future
# experiment type that genuinely has a baseline to compare against. Creative
# Lab V2's own experiment type has no mandatory baseline (see
# core.experiment_simulation.build_concept_arms_result): it compares several
# Creative Concepts, each built to answer the SAME learning question, against
# EACH OTHER. "Outcome" here means "relative to the group's own mean," never
# "relative to a current ad," and there is no "winner" concept: the job is to
# say whether a direction worth developing emerged, not to crown one arm.
#
# Reuses, unchanged, wherever the underlying math doesn't care whether "old"
# is a control or a group mean: _relative_delta, _direction, _format_pct,
# _join_and, and (via simple duck typing on the shared `.outcome` field)
# _evidence_strength/_evidence_strength_reason. Introduces new, purpose-built
# vocabulary (CONCEPT_ASSESSMENT_*, the next-test DIMENSION_* constants)
# rather than forcing the old current-ad ASSESSMENT_*/NEXT_STEP_* enums,
# which are semantically about "return to the current ad" / "scale past the
# current ad" and don't describe "which of several concepts deserves further
# investment."

CONCEPT_ASSESSMENT_DIRECTION_FOUND = "direction_found"
CONCEPT_ASSESSMENT_MIXED = "mixed"
CONCEPT_ASSESSMENT_NO_CLEAR_DIRECTION = "no_clear_direction"
CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE = "insufficient_evidence"

CONCEPT_ASSESSMENT_LABELS = {
    CONCEPT_ASSESSMENT_DIRECTION_FOUND: "Direction found",
    CONCEPT_ASSESSMENT_MIXED: "Mixed result",
    CONCEPT_ASSESSMENT_NO_CLEAR_DIRECTION: "No clear direction",
    CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE: "Insufficient evidence",
}

# What a next test could vary. Deliberately not a mandatory universal
# sequence (see this milestone's own brief): _recommended_next_test below
# only ever proposes ONE of these as its headline suggestion, using the
# rationale text to name 1-2 real alternatives, so a human still decides.
NEXT_TEST_DIMENSION_MESSAGING_ANGLE = "messaging_angle"
NEXT_TEST_DIMENSION_HOOK = "hook"
NEXT_TEST_DIMENSION_FORMAT = "format"
NEXT_TEST_DIMENSION_VISUAL_EXECUTION = "visual_execution"
NEXT_TEST_DIMENSION_PROOF_TREATMENT = "proof_treatment"
NEXT_TEST_DIMENSION_AUDIENCE_FRAMING = "audience_awareness_framing"
NEXT_TEST_DIMENSION_REVISIT_STRATEGY = "revisit_strategy"

NEXT_TEST_DIMENSION_LABELS = {
    NEXT_TEST_DIMENSION_MESSAGING_ANGLE: "Messaging angle",
    NEXT_TEST_DIMENSION_HOOK: "Hook",
    NEXT_TEST_DIMENSION_FORMAT: "Format",
    NEXT_TEST_DIMENSION_VISUAL_EXECUTION: "Visual execution",
    NEXT_TEST_DIMENSION_PROOF_TREATMENT: "Proof treatment",
    NEXT_TEST_DIMENSION_AUDIENCE_FRAMING: "Audience / awareness framing",
    NEXT_TEST_DIMENSION_REVISIT_STRATEGY: "Revisit strategy",
}


@dataclass
class ConceptArmAnalysis:
    """One Creative Concept's comparison against the GROUP MEAN of every
    arm in this same experiment (never against a current ad: this
    experiment type has none). Structurally parallel to CreativeAnalysis
    above, on purpose, so a future shared rendering helper could treat
    either the same way; kept as a separate type rather than reusing
    CreativeAnalysis directly since "delta vs current ad" and "delta vs
    group mean" are different enough facts that conflating them under one
    field name would be misleading.
    """

    concept_id: str
    name: str
    angle: str
    roas_delta_pct: float | None
    ctr_delta_pct: float | None
    cpa_delta_pct: float | None
    purchases_delta_pct: float | None
    outcome: str  # "improved" | "underperformed" | "mixed" | "neutral", relative to the group mean
    interpretation: str


@dataclass
class RecommendedNextTest:
    """A single, concrete suggestion for what to test next, never an
    automatically-launched workflow (this milestone only recommends; see
    this module's own docstring). `dimension` is one of the
    NEXT_TEST_DIMENSION_* constants; `rationale` is the one sentence
    explaining why, and may name 1-2 real alternative dimensions without
    committing to a mandatory sequence.
    """

    dimension: str
    label: str
    rationale: str


@dataclass
class ProposedLearning:
    """A structured, IN-SESSION-ONLY candidate learning (Milestone 23's own
    "Learning Object"): everything a future, human-approved Save Learning
    step would need, without actually being one. `status` stays
    "pending_review" for the life of this object; nothing in this module,
    or anywhere else in this project, ever promotes a ProposedLearning to
    clients/<client>/approved_learnings.json on its own. A human approving
    it is explicit future work this milestone does not implement.
    """

    experiment_id: str
    opportunity_id: str
    product: str
    funnel_stage: str
    variable_tested: str
    concepts_compared: list[str]
    strongest_direction: str | None
    hypothesis_assessment: str
    evidence_strength: str
    learning_statement: str
    limitations: str
    recommended_next_test: RecommendedNextTest
    source: str = "Demo synthetic experiment analysis (Performance Agent preview)"
    status: str = "pending_review"
    generated_by: str = GENERATED_BY_PREVIEW


@dataclass
class ConceptExperimentAnalysis:
    """The Performance Agent's structured output for a Creative Lab V2
    (multi-arm, no-baseline) experiment. Parallel in spirit to
    ExperimentAnalysis above (facts plus this module's own deterministic
    interpretation), but answers a different question: not "did the
    treatment beat the current ad," but "did this comparison of concepts
    point toward a direction worth developing, relative to the learning
    question that was actually asked."
    """

    experiment_id: str
    client_id: str
    opportunity_id: str
    source_finding_id: str
    learning_question: str
    hypothesis: str
    primary_metric: str
    arm_analyses: list[ConceptArmAnalysis] = field(default_factory=list)
    strongest_arm_id: str | None = None
    hypothesis_assessment: str = CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE
    evidence_strength: str = EVIDENCE_WEAK
    evidence_strength_reason: str = ""
    headline: str = ""
    learning_statement: str = ""
    limitations: str = ""
    key_observations: list[str] = field(default_factory=list)
    recommended_next_test: RecommendedNextTest | None = None
    proposed_learning: ProposedLearning | None = None
    data_type: str = "demo_synthetic"
    generated_by: str = GENERATED_BY_PREVIEW


def _group_mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _classify_arm_outcome(arm: CreativeResult, roas_mean: float | None, ctr_mean: float | None) -> str:
    """Reuses _direction/_classify_outcome's exact "ROAS+CTR disagree ->
    mixed" rule, only with the group mean standing in for "old" (the
    current ad, in the baseline experiment type). _direction already
    handles a None/zero mean honestly (no comparable baseline -> "flat"),
    so a 1-arm experiment (mean == that arm's own value) always reads as
    "neutral," never a fabricated direction.
    """
    roas_dir = _direction(arm.roas, roas_mean)
    ctr_dir = _direction(arm.ctr, ctr_mean)
    if {roas_dir, ctr_dir} == {"up", "down"}:
        return OUTCOME_MIXED
    if roas_dir == "up":
        return OUTCOME_IMPROVED
    if roas_dir == "down":
        return OUTCOME_UNDERPERFORMED
    return OUTCOME_NEUTRAL


def _arm_interpretation(name: str, outcome: str, roas_delta: float | None, ctr_delta: float | None) -> str:
    roas_txt = f"{_format_pct(roas_delta)} ROAS" if roas_delta is not None else "ROAS with no comparable group average"
    ctr_txt = f"{_format_pct(ctr_delta)} CTR" if ctr_delta is not None else "CTR with no comparable group average"
    if outcome == OUTCOME_IMPROVED:
        return f"{name} performed above the test's own average ({roas_txt}, {ctr_txt} versus the group average)."
    if outcome == OUTCOME_UNDERPERFORMED:
        return f"{name} performed below the test's own average ({roas_txt}, {ctr_txt} versus the group average)."
    if outcome == OUTCOME_MIXED:
        return f"{name} showed a mixed result against the group average ({roas_txt}, {ctr_txt}): the two metrics moved in different directions."
    return f"{name} performed about the same as the group average ({roas_txt}, {ctr_txt})."


def _build_arm_analysis(arm: CreativeResult, angle: str, roas_mean: float | None, ctr_mean: float | None, cpa_mean: float | None, purchases_mean: float | None) -> ConceptArmAnalysis:
    roas_delta = _relative_delta(arm.roas, roas_mean)
    ctr_delta = _relative_delta(arm.ctr, ctr_mean)
    cpa_delta = _relative_delta(arm.cpa, cpa_mean)
    purchases_delta = _relative_delta(arm.purchases, purchases_mean)
    outcome = _classify_arm_outcome(arm, roas_mean, ctr_mean)

    return ConceptArmAnalysis(
        concept_id=arm.creative_id,
        name=arm.name,
        angle=angle,
        roas_delta_pct=roas_delta,
        ctr_delta_pct=ctr_delta,
        cpa_delta_pct=cpa_delta,
        purchases_delta_pct=purchases_delta,
        outcome=outcome,
        interpretation=_arm_interpretation(arm.name, outcome, roas_delta, ctr_delta),
    )


def _concept_hypothesis_assessment(evidence_strength: str, outcomes: list[str]) -> str:
    """If any arm shows a genuine ROAS/CTR disagreement, the comparison
    itself is noisy ("mixed"), regardless of anything else. Otherwise, any
    arm meaningfully above the group mean means a direction was found
    (worth developing further); if nothing separates from the group at
    all, the comparison simply didn't produce a direction. "Weak" evidence
    always wins the vote first, same discipline as the baseline
    experiment's own _hypothesis_assessment.
    """
    if evidence_strength == EVIDENCE_WEAK or not outcomes:
        return CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE
    outcome_set = set(outcomes)
    if OUTCOME_MIXED in outcome_set:
        return CONCEPT_ASSESSMENT_MIXED
    if OUTCOME_IMPROVED in outcome_set:
        return CONCEPT_ASSESSMENT_DIRECTION_FOUND
    return CONCEPT_ASSESSMENT_NO_CLEAR_DIRECTION


def _concept_headline(assessment: str, strongest_arm: CreativeResult | None) -> str:
    """Careful, evidence-tied wording (this milestone's own explicit
    requirement): never "proven"/"caused"/"guaranteed winner." The
    headline comes from assessment + evidence_strength together (evidence_
    strength is folded in by the caller choosing WHICH branch of assessment
    applies; see analyze_concept_experiment), never from a hardcoded
    assumption that one arm wins.
    """
    if assessment == CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE:
        return "The result is promising, but not settled."
    if assessment == CONCEPT_ASSESSMENT_NO_CLEAR_DIRECTION:
        return "No clear direction emerged from this test."
    if assessment == CONCEPT_ASSESSMENT_MIXED:
        return "Results were mixed across concepts in this test."
    name = strongest_arm.name if strongest_arm else "One concept"
    return f"{name} showed the strongest response in this comparison."


def _learning_statement(
    assessment: str, learning_question: str, strongest_arm: CreativeResult | None, strongest_ca: ConceptArmAnalysis | None
) -> str:
    """The "what we learned" sentence, tied explicitly back to the ORIGINAL
    learning question (this milestone's own central requirement), never a
    generic "X won." Wording is deliberately careful: "directionally
    stronger"/"may be worth developing further," never "proven"/"caused."
    """
    if assessment == CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE:
        return (
            "There isn't enough purchase volume yet to say which framing is directionally stronger; treat this "
            "as an early signal, not a learning."
        )
    if assessment == CONCEPT_ASSESSMENT_NO_CLEAR_DIRECTION:
        return (
            "None of the tested concepts separated from the others in this comparison, so this test does not "
            "yet point toward a direction worth developing further."
        )
    if assessment == CONCEPT_ASSESSMENT_MIXED:
        return (
            "The tested concepts did not agree across metrics in this comparison (one measure favored one "
            "concept, another measure favored a different one), so the result is not yet a clear direction."
        )
    roas_txt = f"{_format_pct(strongest_ca.roas_delta_pct)} ROAS" if strongest_ca and strongest_ca.roas_delta_pct is not None else "stronger ROAS"
    ctr_clause = f" and {_format_pct(strongest_ca.ctr_delta_pct)} CTR" if strongest_ca and strongest_ca.ctr_delta_pct is not None else ""
    name = strongest_arm.name if strongest_arm else "This concept"
    question = learning_question.rstrip("?")
    return (
        f"{name} produced {roas_txt}{ctr_clause} above the test average, giving directional evidence that this "
        f"framing may be worth developing further to help answer: {question}."
    )


def _limitations(evidence_strength: str) -> str:
    base = "One synthetic test is not enough to generalize this across audiences, products, or formats."
    if evidence_strength == EVIDENCE_WEAK:
        return base + " Purchase volume in this test is also small, so treat this as a signal, not a confirmed pattern."
    return base


def _recommended_next_test(assessment: str, strongest_arm: CreativeResult | None) -> RecommendedNextTest:
    """Recommends the next LEARNING QUESTION, never an autonomous action:
    nothing here launches a new workflow or creates a new creative. Only
    ONE dimension is ever the headline suggestion; the rationale names 1-2
    real alternatives so a human still decides, never a hardcoded mandatory
    sequence (this milestone's own explicit instruction).
    """
    if assessment == CONCEPT_ASSESSMENT_INSUFFICIENT_EVIDENCE:
        return RecommendedNextTest(
            dimension=NEXT_TEST_DIMENSION_MESSAGING_ANGLE,
            label=NEXT_TEST_DIMENSION_LABELS[NEXT_TEST_DIMENSION_MESSAGING_ANGLE],
            rationale=(
                "Purchase volume is too small to trust a direction yet. Running this same messaging-angle "
                "comparison longer would help before changing anything else."
            ),
        )
    if assessment == CONCEPT_ASSESSMENT_MIXED:
        return RecommendedNextTest(
            dimension=NEXT_TEST_DIMENSION_MESSAGING_ANGLE,
            label=NEXT_TEST_DIMENSION_LABELS[NEXT_TEST_DIMENSION_MESSAGING_ANGLE],
            rationale=(
                "Keep the opportunity, but test the messaging angles again with stronger separation or more "
                "evidence before moving on to execution-level questions like hook or format."
            ),
        )
    if assessment == CONCEPT_ASSESSMENT_NO_CLEAR_DIRECTION:
        return RecommendedNextTest(
            dimension=NEXT_TEST_DIMENSION_REVISIT_STRATEGY,
            label=NEXT_TEST_DIMENSION_LABELS[NEXT_TEST_DIMENSION_REVISIT_STRATEGY],
            rationale=(
                "The angles tested here did not produce a strong direction. Revisit the creative strategy for "
                "this opportunity before investing in deeper iteration."
            ),
        )
    name = strongest_arm.name if strongest_arm else "the strongest concept"
    return RecommendedNextTest(
        dimension=NEXT_TEST_DIMENSION_HOOK,
        label=NEXT_TEST_DIMENSION_LABELS[NEXT_TEST_DIMENSION_HOOK],
        rationale=(
            f"Rather than testing the messaging angle again, keep {name}'s framing and audience context, and "
            "test how that idea should be executed next, for example its hook, visual format, or proof treatment."
        ),
    )


def _concept_key_observations(arm_analyses: list[ConceptArmAnalysis]) -> list[str]:
    """1-2 concise observations, same spirit as the baseline experiment's
    own _key_observations: never restates the purchase-volume/evidence
    caveat here (that is evidence_strength_reason's exclusive job).
    """
    if not arm_analyses:
        return []
    if len(arm_analyses) == 1:
        return [arm_analyses[0].interpretation]

    by_roas = sorted(arm_analyses, key=lambda ca: ca.roas_delta_pct if ca.roas_delta_pct is not None else 0.0, reverse=True)
    best, worst = by_roas[0], by_roas[-1]
    observations = []
    if best.concept_id != worst.concept_id:
        observations.append(
            f"{best.name} led on ROAS in this comparison, while {worst.name} trailed the group most."
        )
    else:
        observations.append("All concepts landed close to the same ROAS in this comparison.")

    mixed_names = [ca.name for ca in arm_analyses if ca.outcome == OUTCOME_MIXED]
    if mixed_names and len(observations) < 2:
        observations.append(
            f"{_join_and(mixed_names)} showed ROAS and CTR moving in different directions, a sign that "
            "engagement and efficiency gains don't always move together."
        )
    return observations[:2]


def _build_proposed_learning(handoff: dict, analysis: "ConceptExperimentAnalysis") -> ProposedLearning:
    strongest_name = next(
        (ca.name for ca in analysis.arm_analyses if ca.concept_id == analysis.strongest_arm_id), None
    )
    return ProposedLearning(
        experiment_id=analysis.experiment_id,
        opportunity_id=analysis.opportunity_id,
        product=handoff.get("product", ""),
        funnel_stage=handoff.get("funnel_stage", ""),
        variable_tested=handoff.get("variable_to_test", ""),
        concepts_compared=[ca.name for ca in analysis.arm_analyses],
        strongest_direction=strongest_name,
        hypothesis_assessment=analysis.hypothesis_assessment,
        evidence_strength=analysis.evidence_strength,
        learning_statement=analysis.learning_statement,
        limitations=analysis.limitations,
        recommended_next_test=analysis.recommended_next_test,
    )


def analyze_concept_experiment(handoff: dict, result: ExperimentResult) -> ConceptExperimentAnalysis:
    """The Milestone 23 entry point for a Creative Lab V2 (multi-arm,
    no-baseline) experiment: turns a core.experiment_simulation.
    build_concept_arms_result output, plus the handoff it belongs to, into
    a structured ConceptExperimentAnalysis. Called from "Run Demo Test" in
    app_pages/experiments.py exactly once per click, same pattern as
    analyze_experiment; never recomputed on a rerender, never calls an
    LLM, image provider, or paid API.

    result.current_ad_result is expected to be None here (this experiment
    type has no baseline arm); every arm in result.treatment_results is
    compared against the GROUP'S OWN MEAN, computed once from all arms in
    this exact result, never against any other experiment's numbers or a
    hardcoded target.
    """
    arms = result.treatment_results
    roas_mean = _group_mean([a.roas for a in arms])
    ctr_mean = _group_mean([a.ctr for a in arms])
    cpa_mean = _group_mean([a.cpa for a in arms])
    purchases_mean = _group_mean([float(a.purchases) for a in arms])

    arm_meta = {
        c.get("generated_id"): c for c in handoff.get("treatment_ad_package", {}).get("selected_creative_versions", [])
    }
    arm_analyses = [
        _build_arm_analysis(arm, arm_meta.get(arm.creative_id, {}).get("angle", ""), roas_mean, ctr_mean, cpa_mean, purchases_mean)
        for arm in arms
    ]

    min_purchases = min((a.purchases for a in arms), default=0)
    # _evidence_strength only reads `.outcome` off each item, so a list of
    # ConceptArmAnalysis works exactly like a list of CreativeAnalysis here
    # (unchanged, shared function; see this section's own module note).
    evidence_strength = _evidence_strength(min_purchases, arm_analyses)
    assessment = _concept_hypothesis_assessment(evidence_strength, [ca.outcome for ca in arm_analyses])

    strongest_arm = _strongest_observed(arms)
    ca_by_id = {ca.concept_id: ca for ca in arm_analyses}
    strongest_ca = ca_by_id.get(strongest_arm.creative_id) if strongest_arm else None
    strongest_arm_id = strongest_arm.creative_id if (strongest_arm and evidence_strength != EVIDENCE_WEAK) else None

    learning_question = handoff.get("learning_question") or handoff.get("hypothesis", "")

    analysis = ConceptExperimentAnalysis(
        experiment_id=result.experiment_id,
        client_id=result.client_id,
        opportunity_id=handoff.get("opportunity_id", handoff.get("proposal_id", "")),
        source_finding_id=handoff.get("source_finding_id", ""),
        learning_question=learning_question,
        hypothesis=handoff.get("hypothesis", ""),
        primary_metric="ROAS",
        arm_analyses=arm_analyses,
        strongest_arm_id=strongest_arm_id,
        hypothesis_assessment=assessment,
        evidence_strength=evidence_strength,
        evidence_strength_reason=_evidence_strength_reason(evidence_strength, min_purchases),
        headline=_concept_headline(assessment, strongest_arm if strongest_arm_id else None),
        learning_statement=_learning_statement(assessment, learning_question, strongest_arm if strongest_arm_id else None, strongest_ca),
        limitations=_limitations(evidence_strength),
        key_observations=_concept_key_observations(arm_analyses),
        recommended_next_test=_recommended_next_test(assessment, strongest_arm if strongest_arm_id else None),
    )
    analysis.proposed_learning = _build_proposed_learning(handoff, analysis)
    return analysis
