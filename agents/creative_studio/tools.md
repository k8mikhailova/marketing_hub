# Creative Studio Agent: Tools

- `agents.strategist.engine.generate_proposal`: the authoritative
  `ExperimentProposal` Creative Studio builds from. Never re-derives or
  second-guesses it.
- `core.data.load_creative_catalog`: the control creative's real metadata
  (headline, primary text, CTA, format, message style, hook type).
- `core.assets.resolve_creative_image`: the control's source-ad image path,
  or `None`. Never inferred from a filename.
- `agents.creative_studio.engine._load_observed_ad_copy` (via
  `data/<client>/observed_ad_copy.csv`): real Meta Ads Library ad-level
  copy (primary text, headline, description, CTA, observed version count)
  for the handful of creatives where we have it, keyed by `creative_id`.
  Rows carry `data_type="public_ad_library_observed"`; a creative with no
  row falls back to the catalog's own headline/primary text/CTA rather than
  a fabricated Meta value.
- `agents.creative_studio.engine.build_control_ad_package`: assembles the
  `control_ad_package` (ad-level primary text/headline/description/CTA,
  preferring observed copy over the catalog fallback) plus its historical
  synthetic performance via `core.analytics.aggregate_performance`.
- `agents.creative_studio.engine.build_treatment_ad_package`: assembles the
  `treatment_ad_package` from the proposal and the control package: new
  customer-language primary text, headline/description/CTA carried over
  unchanged from the control (the ad-level "keep constant").
- `core.visual_performance.visual_performance_context`: for a given
  product/funnel stage, an evidence-scored read on how visual attributes
  (human presence, product prominence, text density, etc.) have performed,
  each result marked `sufficient` or an honest "not enough data" reason.
  Never manufactures a pattern. Used by `_pick_evidence_informed_direction`
  to steer one (not all 3) of a batch's visual directions; never bypassed
  to compare across an unrelated product or funnel stage.
- `core.visual_performance.attribute_value_provenance`: whether the
  creatives behind one evidence result's attribute-value cell are backed
  by an independently reviewed source image, only heuristic demo-synthetic
  metadata, or a mix. Used only to phrase the evidence-informed role's
  reasoning honestly, never to change whether a pattern counts as
  sufficient.
- `agents.creative_studio.engine._select_batch_roles`: fills exactly one
  evidence-informed, one hypothesis-informed, and one exploratory role per
  batch (never the 3 strongest historical patterns). Groups the 6 fixed
  strategies by their actual rendered on-image headline for this
  ad_package first, so the evidence-informed pick's whole headline-sharing
  group is excluded before the other 2 roles rotate through the rest by
  `batch_index`: guarantees 3 genuinely different on-image headlines every
  batch, and that "Generate 3 More" doesn't repeat the same 3 until the
  pool is exhausted.
- `agents.creative_studio.engine.generate_creative_versions`: the
  deterministic demo generator, producing one batch of 3 `CreativeVersion`s
  per call against the treatment ad package (one per role from
  `_select_batch_roles`: evidence-informed, hypothesis-informed,
  exploratory), each a different visual-direction strategy (control-
  inspired, lifestyle, sensory focus, minimal studio, human moment, bold
  graphic) with its OWN on-image headline and optional supporting
  copy/proof/CTA. `batch_index` rotates the hypothesis-informed and
  exploratory roles through the remaining strategy pool, so repeated
  "Generate 3 More" calls get fresh directions before the pool repeats.
- `agents.creative_studio.engine.validate_creative_versions`: reusable,
  model-agnostic check that a batch stays inside the controlled experiment:
  every version matches the package on `ad_package_id`/`proposal_id`/
  `control_creative_id`/product/funnel stage/format, any stated on-image
  proof equals `proof_to_retain` exactly, no invented number or banned
  performance-claim language, versions visually distinct from each other.
  Deliberately does NOT require identical on-image wording across versions.
- `agents.creative_studio.engine.validate_version_edit`: reusable check
  that an edit to one version didn't touch a protected shared-package
  field. Not wired into the default Creative Lab workflow; kept for
  optional internal/expander use.

`generate_creative_versions` is structured so a future live implementation
(an actual model call deriving visual directions, also informed by
`visual_performance_context` alongside the hypothesis and control) can
replace the deterministic generator without changing this contract or
Creative Lab's page code; see the module docstring in
`agents/creative_studio/engine.py`.

Image generation (batch-requested; demo mode by default, live on request):

- `agents.creative_studio.generation.build_generation_request`: assembles
  the input contract (`GenerationRequest`) straight from one
  `CreativeVersion`'s own on-image fields, plus the control's resolved
  image path, a batch id, and a short brand context. Ad-level copy is never
  part of this request. Identical regardless of demo/live mode.
- `agents.creative_studio.generation.get_creative_resolver`: the ONE seam
  `CREATIVE_GENERATION_MODE` (env var, default `"demo"`) actually branches
  on. Returns a `GenerationRequest -> GeneratedCreative` callable, resolved
  once per batch (fails the whole batch with one message if it can't
  proceed, same contract as `get_default_provider` always had). `"live"`
  mode returns the exact existing path below, unchanged; `"demo"` mode
  returns a resolver against this client's pre-generated demo asset
  manifest (`agents.creative_studio.demo_assets.resolve_demo_creative`,
  zero provider calls). Never exposed as a Streamlit control: an
  application/development configuration, not a marketer setting.
- `agents.creative_studio.demo_assets.resolve_demo_creative`: given a
  `GenerationRequest`, looks up `assets/<client>/generated/
  demo_manifest.json` for an entry whose own recorded proposal/control
  creative/product/funnel stage/concept_id all match exactly, re-verifies
  that entry's image file and metadata.json both still exist and agree
  with each other, and returns a `GeneratedCreative` pointing at that real,
  already-generated image (`generation_source="pre_generated_demo"`;
  `provider`/`model`/`generated_at`/`prompt` stay the REAL original values
  from that image's own generation, never a fabricated "just now" call).
  Any mismatch, missing entry, or missing file raises `ImageGenerationError`
  ("this fixture is unavailable") rather than guessing or reusing a
  different creative's image.
- `agents.creative_studio.demo_assets.rebuild_demo_manifest`: the only
  supported way to add or refresh manifest entries. Scans every real
  `metadata.json` already under `assets/<client>/generated/`, keeping one
  entry per unique `concept_id` (the earliest real generation when more
  than one exists; a metadata file whose own image is missing is excluded
  from consideration entirely, so the manifest can never point at a dead
  file when a working duplicate exists), looks up `product`/`funnel_stage`
  from the catalog via `control_creative_id`. Run by hand after manually
  generating and saving a new batch; never called by the app itself.
- `core.brand_context.creative_context`: a short, prompt-ready client
  context string, `""` while a client's `*.md` files are still
  placeholders.
- `agents.creative_studio.generation.build_prompt`: the actual image
  prompt, built only from `GenerationRequest` fields (EXACT ON-IMAGE COPY
  / ALSO FIXED / THIS VERSION'S VISUAL DIRECTION / REFERENCE / AVOID). Only
  non-empty on-image fields are listed as exact text; an empty field (e.g.
  no on-image CTA) is omitted from the prompt rather than rendered as
  empty or invented. Only ever built/used on the live path.
- `agents.creative_studio.image_provider.ImageGenerationProvider`: the
  one-method provider seam; `OpenAIImageProvider` is the implementation,
  calling OpenAI's `images.edit` API with the control creative as the
  reference image. Reads `OPENAI_API_KEY` from the environment only.
  Untouched by this milestone; only reached when
  `CREATIVE_GENERATION_MODE=live`.
- `agents.creative_studio.generation.generate_creative`: orchestrates one
  live provider call and stores the result via
  `core.assets.save_generated_asset` (`generation_source="live"`). Called
  once per pending slot in Creative Lab's batch loop when in live mode, so
  one version's provider failure never discards another version's success.
- `core.assets.generated_assets_dir` / `save_generated_asset`: where a
  generated image and its metadata sidecar are written; never
  `source_ads/`, never an overwrite.

Live mode is the app's one live model call. Every failure mode (missing
key, auth, timeout, refusal, malformed response, storage failure) raises a
single `ImageGenerationError` with a message safe to show a user directly,
scoped to that one version's generation slot; demo mode raises the same
exception type for a missing/mismatched fixture, so
`app_pages/creative_lab.py`'s error handling doesn't need to know which
mode produced it.
