# Creative Studio Agent

**Core question:** "Turn a human-approved experiment into one Meta-shaped
ad package (primary text, headline, description, CTA), then render several
real, genuinely distinct visual creative versions underneath that same ad,
while preserving the controlled experiment throughout."

**Role:** Two stages, each with its own module. Ad/version development
(`agents/creative_studio/engine.py`) builds TWO `AdPackage`s from an
already-approved `ExperimentProposal`: a `control_ad_package` (the real
existing ad, using observed Meta Ads Library copy when we have it) and a
`treatment_ad_package` (new customer-language primary text; headline,
description, and CTA carried over unchanged from the control as the
ad-level constant). On request, it then produces batches of 3
`CreativeVersion` briefs against the treatment package: distinct VISUAL
executions (a control-inspired composition, a lifestyle setting, a sensory
close-up, etc.), each with its OWN on-image headline/supporting copy/proof/
CTA. Image generation (`agents/creative_studio/generation.py` +
`image_provider.py`) takes one `CreativeVersion` and renders it as a real
image; by default (`CREATIVE_GENERATION_MODE=demo`) this resolves an
already-real, previously-generated image from a fixture manifest with zero
provider calls, for a fast local/demo experience, and only reaches a live
model when explicitly set to `"live"`. Does not decide what to test, discover customer signals, calculate
performance, or select a control: all of that belongs to the Intelligence
Agent and the Creative Strategist, upstream of Creative Studio.

**Central model:** one ad package, many visual creative versions, each
version free to say something different on-image. This mirrors how a real
Meta ad works: one ad-level primary text/headline/description/CTA, several
creative versions underneath it (Brio's own account has exactly this shape
today: brio_cr_004/005/008 already share one real observed ad and each
carries a different on-image treatment). What must NOT drift between
versions of the same package is the true constant set: `ad_package_id`,
`proposal_id`, `control_creative_id`, `product`, `funnel_stage`, `format`,
and (when a version states an on-image proof at all) that proof must match
the package's own `proof_to_retain` exactly. `validate_creative_versions`
enforces exactly that boundary, not sameness of on-image wording.

**Balanced exploration, not "pick the 3 strongest patterns":** each batch
of 3 fills exactly one evidence-informed role, one hypothesis-informed
role, and one exploratory role (`engine.py::_select_batch_roles`). The
evidence-informed role is steered by `core.visual_performance.
visual_performance_context` when a same-product/same-funnel-stage visual
pattern actually clears its own evidence bar; otherwise it falls back to a
hypothesis/control-driven direction and says so. The hypothesis-informed
role is built from the package's own customer-language theme; the
exploratory role is a meaningfully different execution, never a repeat of
the other two. Evidence is always phrased as an associative historical
pattern (never causal language), and its reasoning distinguishes a pattern
backed by an independently reviewed source image from one backed only by
heuristic, demo-synthetic visual metadata (`core.visual_performance.
attribute_value_provenance`), never overstating either.

**Reads:** The approved `ExperimentProposal` (`agents/strategist/
engine.py`), the control creative's row in `creative_catalog.csv`, its
observed Meta Ads Library copy from `data/<client>/observed_ad_copy.csv`
when a row exists for it (blank/unknown rather than fabricated when it
doesn't), its source-ad image via `core/assets.py`, historical synthetic
performance via `core.analytics.aggregate_performance`, and, for image
generation, a short brand context via `core/brand_context.py`.

**Produces:** A `control_ad_package` and a `treatment_ad_package`
(`agents/creative_studio/engine.py::build_control_ad_package`,
`build_treatment_ad_package`), then batches of 3 `CreativeVersion` objects
(`generate_creative_versions`) against the treatment package: a distinct
visual direction, on-image headline, and optional on-image supporting
copy/proof/CTA per version, plus an explicit generation instruction. Once a
human requests generation, a `GeneratedCreative` per version
(`agents/creative_studio/generation.py::generate_creative`): a real image
plus a JSON metadata sidecar, stored under `assets/<client_id>/generated/`,
traceable back to the proposal, ad package, control, and batch.

**Demo vs. live generation:** `CREATIVE_GENERATION_MODE` (env var, default
`"demo"`) decides at exactly one seam
(`generation.py::get_creative_resolver`) whether a batch resolves
pre-generated fixture images (`agents/creative_studio/demo_assets.py`,
matched against a manifest by proposal/control creative/product/funnel
stage/concept_id, never a guess) or reaches the real
`OpenAIImageProvider`. Never a Streamlit control: an application/
development setting, invisible to a marketer, who sees the identical
"Generate Creatives" -> gallery flow either way. A demo-resolved
creative's `provider`/`model`/`generated_at`/`prompt` are always the REAL
values from when that image was actually generated, never a fabricated
"just now" call; only `generation_source` ("pre_generated_demo" vs.
"live") distinguishes how the object now in hand was produced.

**Since Milestone 22, a second, separate model exists alongside the one
above: `CreativeConcept` and `generate_concepts_for_opportunity`.** A
concept varies the MESSAGING ANGLE for one `CreativeOpportunity`
(Problem recognition / Desired outcome / Proof-led: distinct hypotheses
about what moves the audience), never the visual execution of one fixed
ad package the way a `CreativeVersion` does; the two models are not
interchangeable and are not meant to be. All 3 concepts in a family share
the opportunity's own CTA/product/funnel-stage/format (the true
constants); only headline/primary text/reason-to-believe (the tested
variable) differ. `validate_creative_concepts` reuses
`PERFORMANCE_CLAIM_PATTERN`/`_numbers_in`/`_text_too_similar` from this
same module rather than duplicating the claim-safety logic above. Concepts
render through a placeholder ("Creative preview: image generation added
next," `core/ui.py::render_creative_placeholder`); this milestone never
calls the image provider or reuses an existing generated/demo asset for a
new concept, and reconnecting live generation for concepts is explicit
future work at that point; it was done in Milestone 28, see "Creative Studio V3" below.

**Boundaries:** Ad-package generation only runs once a human reaches the
Experiment stage in Creative Lab and requests creative options; no
separate brief-approval step exists (see workflow.md). The true shared
constants (`ad_package_id`, `proposal_id`, `control_creative_id`, product,
funnel stage, format) never change across versions or across a "Generate 3
More" batch, and a version's on-image proof, if present, must equal the
package's `proof_to_retain` exactly: `validate_creative_versions` checks
every batch against those rules before Creative Lab shows it, and the
image-generation prompt (`generation.py::build_prompt`) states only that
version's OWN on-image copy as exact, reproducible text, never the
ad-level copy (which doesn't need to appear inside the image at all).
Observed Meta Ads Library data is copy/creative only, never performance:
spend, CTR, CPA, purchases, and ROAS remain synthetic demo data everywhere,
including inside a `control_ad_package`'s `historical_performance`. In
live mode, image generation calls OpenAI's live image-editing API
(`agents/creative_studio/image_provider.py`); this is the only live model
call in the app, and only in that mode (the default, demo mode, makes
none). Never creates an experiment record, simulates a result, integrates
with Meta, or writes to `approved_learnings.json`, at either stage.

## Creative Studio V3 (Milestone 27): finished, test-ready ads

Creative Studio now produces the FINISHED ad for each Creative Concept, and
Creative Lab is where that happens; Experiments tests the exact ads created
and approved there and never regenerates or reinterprets one.

**Milestone 28.4:** before generation, a concept renders as a creative-
direction BRIEF (core/ui.py::render_creative_brief - angle name, the
concept's own `angle` as "Strategic idea," `why_this_concept_exists` as "Why
we're exploring this"), sharing no visual language with a finished ad (no
image slot, no CTA, no Include control); only a generated concept renders as
an ad (render_generated_ad). The two states are meant to look unmistakably
different, not just differently labeled.

Pipeline (agents/creative_studio/pipeline.py):
`CreativeConcept -> AdExecutionSpec (text step, execution.py) -> image
request (generation.py::build_ad_prompt) -> GeneratedCreative (persisted by
creative_store.py)`. The copy exists as validated data BEFORE any image is
generated; the image model is told exactly which on-image words to render and
is never asked to invent strategy or copy.

- **AdExecutionSpec** holds strategy (concept/opportunity ids, angle,
  intent, learning question, theme, avatar, awareness, product, funnel),
  copy (on-image headline, primary text, Meta headline, description, CTA),
  visual (visual direction, required product, proof to preserve, reference
  creative), experiment (variable changed, constants, why the concept
  exists) and provenance. Python fills every field except the model's five
  (`ExecutionCopy`); the CTA and proof are constants the model cannot alter.
- **Validation** (`validate_execution_spec`): no number absent from the
  approved proof, no performance/certification/health/savings/guarantee/
  testimonial/scientific language, no quotation marks, no reuse of the
  reference ad's headline, ad-realistic length limits, and distinctness
  across the concepts of an opportunity. Failures raise `ExecutionSpecError`
  with the specific issues; nothing is saved and the user can retry.
- **Providers** sit behind narrow seams: `TextGenerationProvider`
  (text_provider.py, `chat.completions.parse` structured output) and
  `ImageGenerationProvider` (image_provider.py: `images.edit` with a
  reference, `images.generate` without). Model ids live only in
  `config.py` (env overrides OPENAI_IMAGE_MODEL / OPENAI_TEXT_MODEL).
- **References** are read-only: the opportunity's existing same-product ad,
  for product appearance only (the prompt forbids reproducing its layout or
  wording); none is forced where none exists.
- **Cost protection:** nothing runs on render or rerun; generation is an
  explicit per-opportunity action; a creative whose `creative_key` already
  exists on disk is returned with zero provider calls; only Regenerate
  bypasses that, and it writes a NEW version (older versions stay); one
  concept's failure never affects another; an image-step retry re-uses the
  cached spec instead of paying for the text step again.
- **Live vs demo:** both resolve into the same `GeneratedCreative`. Live
  produces and saves; demo (no key, no provider) loads what live saved
  (`generation_source="saved"`). A saved creative is only shown while its
  concept's strategy fingerprint still matches.
- The older CreativeVersion / VISUAL_DIRECTION_STRATEGIES / demo_assets
  path is unchanged and unused by Creative Lab's default flow.
