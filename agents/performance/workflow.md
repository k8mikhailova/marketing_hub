# Performance Agent: Workflow

1. Since Milestone 17C, triggered automatically as part of "Run Demo
   Test" on the Experiments page (`app_pages/experiments.py::
   _run_demo_test`): building the `ExperimentResult` and running this
   agent against it happen in the same click, so there is no separate
   "Analyze Results" step and no state where a result exists without its
   analysis. There is still no automatic or scheduled analysis outside
   that one click.
2. Read the `experiment_handoff` dict already in `st.session_state`
   (`hypothesis`, `source_finding_id`) and the `ExperimentResult` just
   built in the same callback. Nothing is rebuilt or re-derived: no new
   proposal, no new simulation, no provider call.
3. For each new creative, compute its `CreativeAnalysis`
   (`_build_creative_analysis`): ROAS/CTR/CPA/purchases deltas versus the
   current ad, a categorical outcome (`_classify_outcome`, on ROAS+CTR
   direction), and a one-sentence interpretation. A small, additive review
   added this milestone (`_cpa_conflict_note`) separately flags, as a
   `key_observations` entry, any creative whose CPA moved the "wrong" way
   relative to its own ROAS move, since CPA and purchases inform the
   narrative but don't drive `_classify_outcome` itself; this rarely fires
   against today's simulated data specifically because
   `core/experiment_simulation.py` holds spend and each creative's own AOV
   constant within one experiment, which mathematically couples ROAS and
   CPA together far more often than not (a disclosed limitation of the
   simulation, not of the check, which stays general).
4. Compute `min_purchases` once (`_min_purchases`, the smallest purchase
   count anywhere in the comparison), then one overall `evidence_strength`
   (`_evidence_strength`, from that count and whether any creative's own
   outcome disagreed across metrics), its paired `evidence_strength_reason`
   (`_evidence_strength_reason`, a one-sentence, real-purchase-count
   explanation, never hardcoded to any one experiment), and one
   `hypothesis_assessment` (`_hypothesis_assessment`, from
   `evidence_strength` and the SET of per-creative outcomes, never an
   average).
5. Derive `best_observed_creative_id` (`None` when evidence is weak),
   `recommended_next_step`, `summary`, and `key_observations`, all as pure
   functions of the facts computed in steps 3-4. Since Milestone 17C.1,
   `summary` and `key_observations` deliberately never restate the
   purchase-volume/evidence-tier caveat (a browser review found it
   repeated up to 4 times on the results page); that caveat lives
   exclusively in `evidence_strength_reason` from step 4, and
   `key_observations` is capped at 2 genuinely useful entries instead of
   2-4.
6. Since Milestone 17C.2, also derive the results page's own hero and
   findings fields, all still pure functions of facts already computed:
   `headline_creative_id`/`headline` (`_strongest_observed`/`_headline`:
   the highest-ROAS new creative, ALWAYS populated regardless of
   `evidence_strength`, deliberately unlike `best_observed_creative_id`,
   since the results hero must show a concrete result even under "weak"
   evidence, paired with the evidence caveat right beside it, never
   presented as a decided winner); `ai_findings`
   (`_build_ai_findings`: 2-4 findings grouping creatives by their
   already-computed outcome, adding any `_cpa_conflict_note` entries, and
   a `_cross_creative_pattern` finding that reads
   `handoff["treatment_ad_package"]["selected_creative_versions"]`'s
   `concept_name`/`on_image_proof` fields, ALIGNED BY POSITION with
   `treatment_results` since `build_experiment_result` builds them from
   that same list in that same order, returning `None` whenever the
   metadata doesn't actually differ between the strongest and weakest
   creative); `recommendation_note` (`_recommendation_note`: one sentence
   distinguishing a RESULT from something worth saving as a LEARNING,
   phrased by the headline creative's own outcome and evidence tier).
7. Return one `ExperimentAnalysis`, stored in
   `st.session_state["experiment_analysis"]` alongside the
   `ExperimentResult` in `st.session_state["experiment_result"]`. The
   Experiments page renders both together as one results experience,
   redesigned in Milestone 17C.2 around three questions: a hero (what
   happened), a performance matrix plus "What the AI found" (what the
   system learned), and a recommendation-first block (what to do next),
   all reading conservative, human-facing display labels
   (`EVIDENCE_STRENGTH_LABELS`, `OUTCOME_LABELS`, `NEXT_STEP_LABELS`, the
   last rewritten in Milestone 17C.1 to action-oriented phrasing) rather
   than the backend enum values directly.
8. "Reset Demo Test" clears the stored `ExperimentResult`, this analysis,
   and any temporary human decision together, so replaying the demo test
   and re-analyzing it reproduces the exact same output every time.
9. Never writes to `clients/<client>/approved_learnings.json`: the
   results page's "Recommended next step" buttons only set a temporary
   `st.session_state` value for inspecting the decision UX, never save
   durable memory. The action SET itself depends on `evidence_strength`,
   decided once by the page, never by this module: "Continue Test" / "End
   Experiment" under `weak` ("Limited") evidence, since there may not be a
   learning yet worth naming at that tier; "Save Learning" / "Run Another
   Test" / "Reject" once evidence clears `weak`. Turning an
   `ExperimentAnalysis` into durable, approved memory is still a future,
   human-approval step, not something this agent or any of these buttons
   does on its own.
