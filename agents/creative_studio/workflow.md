# Creative Studio Agent: Workflow

1. Triggered when a human reaches Creative Lab's Experiment stage for an
   already-generated `ExperimentProposal` and clicks "Generate Creatives."
   No separate brief-approval step exists: the proposal itself is the
   approved experiment plan.
2. Build the `control_ad_package`
   (`agents.creative_studio.engine.build_control_ad_package`): the control
   creative's real ad-level copy (observed Meta Ads Library copy when we
   have it for that creative, else the catalog's own headline/primary
   text/CTA) plus its historical synthetic performance.
3. Build the `treatment_ad_package`
   (`build_treatment_ad_package`): new customer-language primary text,
   with headline/description/CTA carried over unchanged from the control
   (the ad-level constant). This package is fixed for the rest of the
   flow; regenerating creative versions never changes it.
4. Generate one batch of 3 `CreativeVersion`s against the treatment
   package (`generate_creative_versions`), one per role
   (`_select_batch_roles`): evidence-informed (steered by same-product/
   same-funnel-stage visual-performance evidence when it qualifies, else a
   hypothesis/control-driven fallback), hypothesis-informed (built from the
   package's own customer theme), and exploratory (a meaningfully different
   execution). Each version has its own on-image headline and optional
   supporting copy/proof/CTA. Validate the batch
   (`validate_creative_versions`) before generating any image: same package
   identifiers and control across all 3, any stated on-image proof matches
   the approved proof exactly, no unsupported performance claim, versions
   visually distinct. A failure here means a bug in the generator itself,
   not a normal outcome.
5. For each version in the batch, independently: build a
   `GenerationRequest` (`agents.creative_studio.generation.
   build_generation_request`) from that version's own on-image fields,
   then resolve it via `get_creative_resolver` (`CREATIVE_GENERATION_MODE`,
   default `"demo"`). In demo mode this matches the request against
   `assets/<client>/generated/demo_manifest.json` and returns an existing,
   real, already-generated image with zero provider calls; in live mode
   it builds the prompt (`build_prompt`) and calls the configured
   `ImageGenerationProvider` (`OpenAIImageProvider`) exactly as before this
   mode existed. One version's failure (a missing/mismatched fixture in
   demo mode; missing key, auth, timeout, refusal, malformed response in
   live mode) never discards another version's successful result.
6. In live mode, store each successful result
   (`core.assets.save_generated_asset`); in demo mode nothing is written,
   since nothing was generated. Either way, return a `GeneratedCreative`
   per version to Creative Lab, `generation_source` marking which path
   produced it.
7. Creative Lab shows the control alongside a gallery of the generated
   versions (successful, pending, or failed), a compact "View ad copy"
   expander for the treatment package's primary text/headline/description/
   CTA, lets the human select any number of them (0, 1, 2, or all 3+),
   retry an individual failed slot without touching the others, or request
   another batch ("Generate 3 More") against the SAME treatment package,
   appended to the gallery rather than replacing it.
8. Selecting one or more creatives and clicking "Continue to Experiment"
   builds `st.session_state["experiment_handoff"]`: the hypothesis,
   customer insight, variable being tested, constants, the full
   `control_ad_package` (copy, source creative, historical synthetic
   performance), and the full `treatment_ad_package` (copy, plus each
   selected creative version's generated id, image path, visual direction,
   and on-image copy). No experiment record, no Meta integration, no
   `approved_learnings.json` write happens here: building and launching a
   real experiment from this handoff is future work.
