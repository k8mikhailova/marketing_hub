# Performance Agent: Tools

- `agents.performance.engine.analyze_experiment(handoff, result)`: the one
  entry point. Takes the `experiment_handoff` dict (for `hypothesis` and
  `source_finding_id`, traceability back to the original Customer
  Signal/Finding, no new state) and a `core.experiment_simulation.
  ExperimentResult` (for every number), and returns one
  `ExperimentAnalysis`. Since Milestone 17C, called once automatically
  from `app_pages/experiments.py::_run_demo_test`, the same click that
  builds the `ExperimentResult` (there is no separate "Analyze Results"
  step); never recomputed on a rerender, never calls an LLM, the image
  provider, or any paid API.
- `agents.performance.engine._build_creative_analysis`: one new creative's
  `CreativeAnalysis` (ROAS/CTR/CPA/purchases deltas vs. the current ad,
  each `None` rather than a fabricated number when the baseline is zero;
  a categorical `outcome`; a one-sentence `interpretation`).
- `agents.performance.engine._classify_outcome`: `"improved"` /
  `"underperformed"` / `"mixed"` / `"neutral"`, decided on ROAS (this
  experiment's own stated primary measure) and CTR (the metric most
  attributable to a creative's own execution). Reuses
  `core.analytics.PERFORMANCE_MIN_RELATIVE_GAP`, the same non-noise gap
  `message_style_leaders`/`attribute_style_leaders` already require, so a
  small, plausibly-noise move never gets called a real change. When ROAS
  and CTR disagree, that disagreement IS the `"mixed"` outcome, never
  averaged away.
- `agents.performance.engine._min_purchases`: the smallest purchase count
  anywhere in the comparison (current ad included), computed exactly once
  per `analyze_experiment` call and threaded into `_evidence_strength`,
  `_evidence_strength_reason`, and `_key_observations`, rather than each
  recomputing it independently.
- `agents.performance.engine._evidence_strength`: a 3-tier read
  (`weak` / `moderate` / `strong`) driven by `_min_purchases`'s count
  against `EVIDENCE_WEAK_PURCHASES_FLOOR` (5) and
  `core.analytics.PERFORMANCE_MIN_PURCHASES` (15, the app's own existing
  "trust this comparison" floor, reused here for the `"strong"` tier), and
  demoted from `"strong"` to `"moderate"` whenever any creative's own
  outcome is `"mixed"`, since cross-metric disagreement is itself weaker
  evidence even at good volume. Since Milestone 17C, the UI never shows
  these backend tier names directly: `EVIDENCE_STRENGTH_LABELS` maps them
  to "Limited" / "Directional" / "Moderate," and even the best tier
  (`strong`) never displays as "Strong," since nothing in this synthetic
  demo experiment supports more than a directional read regardless of
  purchase count.
- `agents.performance.engine._evidence_strength_reason`: a one-sentence,
  real-purchase-count explanation paired with `evidence_strength` (e.g.
  "Purchase volume is still small (4 purchases), so this is a promising
  signal rather than a reliable learning" since Milestone 17C.2's
  explicit RESULT-vs-LEARNING vocabulary), generated from the actual
  evidence state, never hardcoded to any one experiment.
- `agents.performance.engine._cpa_conflict_note`: a small, additive check
  (Milestone 17C) for whether a creative's CPA moved the "wrong" way
  relative to its own ROAS move (both worsening or both improving in a
  way that disagrees, by a real non-noise margin on each), surfaced since
  Milestone 17C.2 as an `ai_findings` entry (moved from `key_observations`
  in 17C/17C.1) so a material CPA/ROAS disagreement is never silently
  hidden just because ROAS+CTR alone drive `_classify_outcome`. Does not
  change the outcome classifier itself. Verified correct and general via
  a hand-crafted test, but rarely or never fires against today's
  simulated data specifically, since `core/experiment_simulation.py`
  holds spend and each creative's own AOV constant within one experiment,
  which mathematically couples ROAS and CPA together far more often than
  not; a disclosed limitation of the simulation, not of this check.
- `agents.performance.engine._strongest_observed` (Milestone 17C.2): the
  highest-ROAS new creative, regardless of `evidence_strength`.
  DELIBERATELY different from `_best_observed_creative_id` below (which
  stays `None` under weak evidence, for a downstream-traceability
  reason): this one purely names which creative the results page's hero
  should headline, since the hero must show a concrete result even under
  "Limited" evidence, paired with the evidence caveat right beside it.
  Never used to drive `hypothesis_assessment` or `evidence_strength`
  themselves.
- `agents.performance.engine._headline` (Milestone 17C.2): the ONE
  sentence the results page's hero renders without scrolling, phrased by
  the headline creative's own outcome ("showed the strongest result" /
  "came closest to the current ad, but still underperformed it" / "had
  the strongest ROAS, though its results were mixed" / "performed about
  the same"), so an all-underperform batch is never framed as though
  something "won." The evidence caveat is a separate sentence
  (`evidence_strength_reason`), not folded in here.
- `agents.performance.engine._build_ai_findings` (Milestone 17C.2): 2-4
  compact findings for "What the AI found," replacing the earlier
  generic "What we learned" text block. Groups creatives by their
  already-computed `outcome` (never a new signal) to name which
  improved/underperformed/were mixed, adds up to 2 `_cpa_conflict_note`
  entries, and adds one `_cross_creative_pattern` finding when the data
  supports it, capped at 4 total.
- `agents.performance.engine._cross_creative_pattern` (Milestone 17C.2):
  connects performance back to an actual tested creative decision, using
  ONLY fields that already exist on `CreativeVersion` and already reached
  this module via the handoff (`concept_name`, `on_image_proof`): never a
  new classification invented from free text. Returns `None` (never a
  forced, unsupported comparison) whenever metadata for either the
  strongest or weakest creative is missing, or when the two don't
  actually differ on either dimension. Deliberately associative language
  ("this may suggest," "is consistent with"), never causal.
- `agents.performance.engine._recommendation_note` (Milestone 17C.2): one
  sentence connecting the headline creative to what a human can actually
  do next, explicitly distinguishing a RESULT ("X produced ROAS Y") from
  something worth saving as a LEARNING. "Weak" evidence never implies a
  learning is ready to save, regardless of how promising the headline
  creative looks; deliberately does not repeat the hero's own "purchase
  volume" phrase (a real duplicate-caveat regression caught and fixed
  during this milestone's own testing).
- `agents.performance.engine._hypothesis_assessment`: rule-grounded, never
  pass/fail. `"weak"` evidence always forces `insufficient_evidence`
  regardless of how a delta looks; otherwise reads the SET of per-creative
  outcomes (any `improved`+`underperformed` disagreement, or any
  individually `"mixed"` creative, makes the whole assessment `"mixed"`).
  The vocabulary is capped at `"supported_directionally"`, never
  `"proven"`/`"confirmed"`, at any evidence level.
- `agents.performance.engine._recommended_next_step`: a bounded advisory
  category for a human marketer (`test_again` / `scale_cautiously` /
  `iterate_creative` / `return_to_current` / `needs_more_data`), derived
  only from `hypothesis_assessment` and `evidence_strength`. Never an
  autonomous action; never touches Meta or writes a learning. Displayed
  through `NEXT_STEP_LABELS`, rewritten in Milestone 17C.1 to
  action-oriented phrasing ("Collect more data," "Run another test," "Try
  another creative direction," "Keep current ad," "Continue testing
  cautiously") rather than the earlier status-sounding wording ("Needs
  more data," "Test again"); the backend enum values are unchanged.
- `agents.performance.engine._best_observed_creative_id`: the
  highest-ROAS new creative, purely as an observed fact for traceability,
  `None` whenever evidence is `"weak"`. Never labeled a "winner," and
  nothing else in the analysis is derived from it.
- `agents.performance.engine._summary` / `_key_observations`: deterministic
  template-based narration over the already-computed facts above (string
  formatting, not natural-language generation); the same templates apply
  whether an experiment has 1 or 6 new creatives. Since Milestone 17C.1,
  neither restates the purchase-volume/evidence-tier caveat
  (`evidence_strength_reason` is its one place); `_key_observations`
  takes only `(treatments, creative_analyses)` now (the `evidence_
  strength`/`min_purchases` parameters it used only for that removed
  caveat line were dropped) and returns at most 2 entries, down from 2-4.

Reused, not duplicated: `core.analytics.PERFORMANCE_MIN_PURCHASES` and
`PERFORMANCE_MIN_RELATIVE_GAP`, the same constants Marketing Intelligence
and Creative Studio's own evidence-informed direction seam already hold
comparisons to, so this agent's evidence bar is consistent with the rest
of the app, not a separately invented one.
