# Performance Agent

**Core question:** "What did this experiment actually show, and how
confident should we be?"

**Role:** Turns one already-computed `core.experiment_simulation.
ExperimentResult` (plus the `experiment_handoff` it belongs to) into a
structured `ExperimentAnalysis`: what happened, how each new creative
compared with the current ad, whether the experiment supports the
hypothesis, how strong that evidence is, and a bounded recommendation for
a human marketer. Never blindly declares the highest-ROAS creative a
winner: an "improved" result on a tiny sample still reads as
`insufficient_evidence`, and a batch where one creative wins while another
loses reads as `mixed`, never a verdict either way on the hypothesis
itself.

**Reads:** One `ExperimentResult` (`current_ad_result` and
`treatment_results`, already self-consistent counts and rates; see
`core/experiment_simulation.py`) plus the `experiment_handoff` dict
Creative Lab already built, for `hypothesis` and `source_finding_id`.
Never recomputes ROAS/CTR/CPA/spend/purchases itself, never calls an LLM,
and never touches `data/<client>/meta_ads.csv` directly: every number it
reasons over was already computed and validated upstream.

**Produces:** One `ExperimentAnalysis`
(`agents/performance/engine.py::analyze_experiment`): a `CreativeAnalysis`
per new creative (quantitative deltas plus a categorical outcome and a
one-sentence interpretation, never prose alone), an overall
`hypothesis_assessment` (`supported_directionally` / `mixed` /
`not_supported` / `insufficient_evidence`, deliberately never "proven" or
"confirmed"), a 3-tier `evidence_strength` (`weak` / `moderate` /
`strong`, driven by purchase-count floors and cross-metric consistency)
plus a one-sentence `evidence_strength_reason` naming the actual purchase
count behind that tier (Milestone 17C.1: this is now the ONE place that
caveat is stated; `summary` and `key_observations` were both trimmed to
stop separately restating it, after a browser review found the same
"purchase volume is small" idea appearing up to 4 times on one page), a
plain-English `summary`, 1-2 genuinely useful `key_observations`
(including, when present, a note on any creative whose CPA moved opposite
its ROAS, since CPA/purchases inform the narrative but don't drive the
outcome classification below), and a bounded `recommended_next_step`
(`test_again` / `scale_cautiously` / `iterate_creative` /
`return_to_current` / `needs_more_data`).

Since Milestone 17C.2, also produces the results page's own results-hero
and findings fields: `headline_creative_id`/`headline` (the highest-ROAS
new creative and a one-sentence, outcome-hedged narration of it,
DELIBERATELY always populated even under "weak" evidence, unlike
`best_observed_creative_id` below, since the results hero must show a
concrete result no matter the evidence tier, paired with the evidence
caveat right beside it), `ai_findings` (2-4 compact findings replacing the
UI's earlier "What we learned" text: strongest/weakest execution, any
genuine CPA-vs-ROAS conflict, and a cross-creative pattern connecting
performance back to an actual tested creative decision such as an
in-image proof claim or visual direction, using existing `CreativeVersion`
metadata reached via the handoff, never a category invented from free
text, and omitted whenever the metadata doesn't actually support one),
and `recommendation_note` (one sentence distinguishing a RESULT from
something worth saving as a LEARNING, never implying "Limited" evidence
has produced a durable pattern).

Since Milestone 17C, the backend tier/enum names above are never shown to
a marketer directly: `app_pages/experiments.py` maps them through this
module's own `EVIDENCE_STRENGTH_LABELS` and `OUTCOME_LABELS` (alongside
the earlier `ASSESSMENT_LABELS`/`NEXT_STEP_LABELS`) to conservative,
human-facing wording, e.g. even the best evidence tier (`strong`) displays
as "Moderate," never "Strong" or "Confirmed," since nothing in this
synthetic demo experiment supports more than a directional read.
`NEXT_STEP_LABELS` itself was rewritten in Milestone 17C.1 to
action-oriented phrasing a marketer would say out loud ("Collect more
data," "Run another test," "Try another creative direction," "Keep
current ad," "Continue testing cautiously") rather than the earlier
status-sounding wording; the backend `NEXT_STEP_*` values are unchanged.

**Since Milestone 23, this agent has a second, parallel analysis for a
second, parallel experiment type.** Everything above describes the
current-ad-vs-treatments analysis (`analyze_experiment`), UNCHANGED, kept
for a future experiment type that genuinely has a baseline. Creative Lab
V2's own experiment type (several Creative Concepts built to answer ONE
learning question, no mandatory baseline; see `agents/strategist/
creative_plan.py`) is analyzed by the new `analyze_concept_experiment`
instead: each concept ARM is compared against the experiment's own GROUP
MEAN, never a current ad, producing `ConceptArmAnalysis` per arm, a
`CONCEPT_ASSESSMENT_*` (`direction_found` / `mixed` / `no_clear_direction`
/ `insufficient_evidence`, deliberately not the current-ad
`ASSESSMENT_*` vocabulary), a `learning_statement` tied explicitly back to
the ORIGINAL learning question (never a generic "X won"), a
`RecommendedNextTest` (one concrete next dimension to investigate, e.g.
hook/format/visual execution/revisit strategy, never a hardcoded mandatory
sequence, never "scale the winner"), and a `ProposedLearning`: a
structured, in-session-only candidate learning
(`status="pending_review"` always) that a FUTURE, human-approved Save
Learning step could promote, never something this agent writes to
`approved_learnings.json` itself. This agent still never decides what to
test next on anyone's behalf: it recommends a learning question, it does
not launch one.

**Boundaries:** Never writes to `clients/<client>/approved_learnings.json`
(a future, human-approved Save Learning step does that; the results
page's "Recommended next step" section only sets a temporary
`st.session_state` value, an action set that itself depends on
`evidence_strength`: "Continue Test"/"End Experiment" under
"Limited" evidence, "Save Learning"/"Run Another Test"/"Reject"
otherwise); never makes an autonomous campaign decision or a Meta call;
never claims statistical significance or causality this synthetic demo
experiment can't support. Since Milestone 17C, called automatically as
part of "Run Demo Test" in `app_pages/experiments.py` (there is no
separate "Analyze Results" step), exactly once per demo test, never
recomputed on a rerender.
