"""Turns one CreativeVersion (a visual execution of an AdPackage's
treatment) into a real, reference-based generated image, via an
ImageGenerationProvider (agents/creative_studio/image_provider.py).

CreativeVersion -> GenerationRequest -> ImageGenerationProvider -> GeneratedCreative

This module owns prompt construction and generated-asset bookkeeping; it
never talks to a provider's API directly (that's image_provider.py's job)
and never decides what should change or stay constant (that was already
decided, and validated, when the version was generated in
agents/creative_studio/engine.py). Concept/version generation answers "what
creative execution should we make?"; this module and image_provider.py only
answer "render this already-approved execution."

Boundaries:
- Never reinterprets the experiment: build_generation_request copies fields
  straight off the selected CreativeVersion, the same object that was
  already validated against its AdPackage. No new copy, product, or claim
  is invented here.
- AD-LEVEL copy (an AdPackage's primary_text/headline/description/cta)
  does not need to appear inside the image and is never part of the
  prompt; only a CreativeVersion's own ON-IMAGE fields (on_image_headline/
  supporting_copy/proof/cta) are marked exact and reproducible. Two
  versions of the same package may have completely different on-image
  wording, matching how Brio's own real ads vary headlines across creative
  versions of one ad (see the module docstring in agents/creative_studio/
  engine.py).
- Nothing here is Brio- or theme-specific: build_prompt is built entirely
  from GenerationRequest fields, so the same code path produces a correct
  prompt for Bottled water frustration, or any future client and finding.
- Generated assets never land in assets/<client_id>/source_ads/ and never
  overwrite a source ad; see core/assets.py::save_generated_asset.

Demo vs. live generation mode (Milestone: pre-generated demo asset mode):
CREATIVE_GENERATION_MODE (env var, default "demo") decides, at exactly one
seam, get_creative_resolver(), whether "Generate Creatives" resolves
pre-generated fixture images (agents/creative_studio/demo_assets.py, zero
provider calls) or reaches the real ImageGenerationProvider via
generate_creative() below, unchanged. Nothing about build_generation_
request, build_prompt, or generate_creative() itself changes between the
two modes; only which function turns a GenerationRequest into a
GeneratedCreative differs.
"""
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agents.creative_studio.engine import CreativeVersion
from agents.creative_studio.execution import AdExecutionSpec
from agents.creative_studio.image_provider import (
    DEFAULT_QUALITY,
    DEFAULT_SIZE,
    ImageGenerationError,
    ImageGenerationProvider,
    get_default_provider,
)
from core.assets import resolve_creative_image, save_generated_asset
from core.brand_context import creative_context

# Which generation path "Generate Creatives" actually takes. "demo" (the
# default, for local development and the interview demo alike) resolves
# pre-generated fixture images with zero provider calls; "live" reaches
# the real OpenAIImageProvider exactly as this module always has. Read
# from the environment (the same .env-file/os.environ convention
# OPENAI_API_KEY already uses, see app.py's load_dotenv() call), never a
# Streamlit UI control: this is an application/development configuration,
# not something a marketer chooses.
CREATIVE_GENERATION_MODE_DEMO = "demo"
CREATIVE_GENERATION_MODE_LIVE = "live"

# Mirrors agents/creative_studio/engine.py's own on-image-copy screen: a
# generation prompt must forbid the same kind of drift a version's own
# fields are validated against, so the two stages can't disagree about
# what's out of bounds.
PROHIBITED_CHANGES = [
    "Changing the offer",
    "Inventing a new claim",
    "Changing the product",
    "Changing the CTA beyond what is specified below",
    "Introducing a second marketing hypothesis",
    "Changing the on-image copy simply to create visual variety",
]


@dataclass
class GenerationRequest:
    """Creative Studio's live-generation input contract: everything the
    image provider needs to render one already-approved CreativeVersion,
    and nothing it's allowed to reinterpret. Every field traces back to the
    version (itself already validated against its AdPackage) or to this
    client's own brand files; nothing here is invented at generation time.
    batch_id ties this request to the batch of 3 it was generated
    alongside, for traceability only. on_image_supporting_copy/proof/cta
    are "" when this version doesn't use them: an empty field is never
    forced into the prompt as text to render.
    """

    client_id: str
    proposal_id: str
    concept_id: str
    control_creative_id: str
    control_image_path: Path
    product: str
    funnel_stage: str
    format: str
    on_image_headline: str
    on_image_supporting_copy: str
    on_image_proof: str
    on_image_cta: str
    variable_to_test: str
    constants_preserved: list[str]
    visual_direction: str
    generation_instruction: str
    batch_id: str = ""
    brand_context: str = ""
    size: str = DEFAULT_SIZE
    quality: str = DEFAULT_QUALITY


@dataclass
class GeneratedCreative:
    """One real, generated image and the trace back to the version, the
    proposal, and the control creative it was rendered from. Every id here
    is preserved from GenerationRequest, never reconstructed from display
    text, so the chain (evidence -> finding -> proposal -> ad package ->
    control -> creative version -> generated creative) always stays
    intact.

    generation_source distinguishes how THIS object was produced: "live"
    means a real provider call just happened (generate_creative, below);
    "pre_generated_demo" (agents/creative_studio/demo_assets.py) means the
    image itself is real AI output from a past live call, but resolving
    IT just now made no provider call at all. provider/model/generated_at/
    prompt always describe the real generation event that produced the
    image bytes, never a fabricated "just now" timestamp or response, in
    either case.
    """

    generated_id: str
    proposal_id: str
    concept_id: str
    control_creative_id: str
    client_id: str
    batch_id: str
    image_path: Path
    metadata_path: Path
    provider: str
    model: str
    generated_at: str
    prompt: str
    generation_source: str = "live"
    # Milestone 27 (Creative Studio V3): a finished ad keeps its structured
    # execution spec (copy, strategy, experiment fields) SEPARATE from the
    # image, plus versioning and reference provenance. All optional with
    # defaults so the older CreativeVersion-based flow (and demo_assets.py)
    # keeps constructing this object unchanged. generation_source is "live"
    # when a provider call just produced it and "saved" when it was loaded
    # from disk: the SAME representation either way.
    ad_spec: AdExecutionSpec | None = None
    version: int = 1
    creative_key: str = ""
    plan_fingerprint: str = ""
    reference_asset_paths: list[str] = field(default_factory=list)
    data_type: str = ""


def build_generation_request(
    client_id: str, variable_to_test: str, version: CreativeVersion, batch_id: str = ""
) -> GenerationRequest:
    """Assemble a GenerationRequest from an already-generated, already-
    validated CreativeVersion. Pure data assembly: every value comes
    straight from the version, the version's own control image resolution,
    or this client's creative context, never reinvented here.

    Raises ImageGenerationError if the control creative has no resolvable
    source image: reference-based generation has nothing to reference
    without one, and Creative Lab is expected to have already disabled the
    "Generate" action in this case rather than let a click reach this far.
    """
    control_image_path = resolve_creative_image(client_id, version.control_creative_id)
    if control_image_path is None:
        raise ImageGenerationError(
            f"Control creative {version.control_creative_id} has no source image to use as a reference."
        )

    return GenerationRequest(
        client_id=client_id,
        proposal_id=version.proposal_id,
        concept_id=version.concept_id,
        control_creative_id=version.control_creative_id,
        control_image_path=control_image_path,
        product=version.product,
        funnel_stage=version.funnel_stage,
        format=version.format,
        on_image_headline=version.on_image_headline,
        on_image_supporting_copy=version.on_image_supporting_copy,
        on_image_proof=version.on_image_proof,
        on_image_cta=version.on_image_cta,
        variable_to_test=variable_to_test,
        constants_preserved=list(version.constants_preserved),
        visual_direction=version.visual_direction,
        generation_instruction=version.generation_instruction,
        batch_id=batch_id,
        brand_context=creative_context(client_id),
    )


def build_prompt(request: GenerationRequest) -> str:
    """The actual image-generation prompt, built entirely from
    GenerationRequest fields: no theme, product, or copy is hardcoded, so
    this produces a correct prompt for any proposal/version, current or
    future.

    Only this version's own ON-IMAGE fields are marked exact/reproducible;
    an AdPackage's ad-level primary_text/headline/description never appear
    here at all, since ad-level copy doesn't need to appear inside the
    image (that distinction is the whole point of this milestone's model).
    An empty on-image field (e.g. no on_image_cta) is omitted from the
    prompt entirely, never rendered as empty text or invented. Structure
    mirrors OpenAI's own documented best practice for reference-image
    editing: separate what changes from what must be preserved, state
    identity/constraints explicitly.
    """
    exact_copy_lines = [f'On-image headline:\n"{request.on_image_headline}"']
    if request.on_image_supporting_copy:
        exact_copy_lines.append(f'On-image supporting line:\n"{request.on_image_supporting_copy}"')
    if request.on_image_proof:
        exact_copy_lines.append(f'On-image proof callout:\n"{request.on_image_proof}"')
    if request.on_image_cta:
        exact_copy_lines.append(f'On-image CTA text:\n"{request.on_image_cta}"')

    exact_copy_block = (
        "EXACT ON-IMAGE COPY - DO NOT REWRITE OR PARAPHRASE\n\n"
        + "\n\n".join(exact_copy_lines)
        + "\n\nReproduce this text exactly as written, character for character, and include ONLY the on-image "
          "text listed above (if a field such as a CTA isn't listed, omit it from the image rather than "
          "inventing one). Do not invent additional marketing claims, do not paraphrase, do not change any "
          "percentages or numbers, and do not add feature claims that are not supplied above."
    )
    fixed_lines = [
        f"Product: {request.product}",
        f"Format: {request.format}",
        f"Funnel stage: {request.funnel_stage}",
        f"Experiment variable being tested: {request.variable_to_test}",
    ]

    sections = [
        "You are creating one visual creative version of an approved, controlled marketing-creative experiment. "
        "Other visual versions of this same ad may use different on-image wording while expressing the same "
        "approved message strategy; this is a visual/product reference, not a request for a pixel-identical copy.",
        exact_copy_block,
        "ALSO FIXED (do not change):\n" + "\n".join(f"- {line}" for line in fixed_lines),
        "THIS VERSION'S VISUAL DIRECTION (only this may change - background, composition, crop, product "
        f"emphasis, lifestyle vs. studio treatment, visual hierarchy):\n{request.visual_direction}",
        "REFERENCE:\nThe attached image is the control creative for this product. Use it as the strongest "
        "visual and product reference, and keep the brand identity, product design, and packaging it shows.",
        "AVOID:\n" + "\n".join(f"- {line}" for line in PROHIBITED_CHANGES),
    ]
    if request.brand_context:
        sections.append(f"BRAND CONTEXT:\n{request.brand_context}")
    return "\n\n".join(sections)


def build_ad_prompt(spec: AdExecutionSpec, reference_available: bool, brand_context: str = "") -> str:
    """The image-generation prompt for ONE finished ad, built entirely from
    an already-validated AdExecutionSpec (no theme, product or copy is
    hardcoded here). The image model is told EXACTLY which words to render;
    it is never asked to invent strategy or copy. Only the short on-image
    headline is printed in the image: the primary text, Meta headline,
    description and CTA live outside it and are deliberately absent from
    this prompt. Sections: BRAND / PRODUCT, AUDIENCE, STRATEGIC CONCEPT,
    MESSAGE TO COMMUNICATE, EXACT ON-IMAGE COPY, VISUAL DIRECTION, REFERENCE
    IMAGE GUIDANCE, MUST PRESERVE, MUST AVOID. Meant for a details/debug
    view, not the default marketer UI.
    """
    brand = f"Product: {spec.required_product}\nApproved proof to stay consistent with: {spec.proof_to_preserve}"
    if brand_context:
        brand += f"\n{brand_context}"
    reference = (
        "The attached image is a reference for the product's real appearance and the brand's visual identity ONLY. "
        "Keep the product design and packaging recognizable. Do NOT reproduce the reference ad's composition, "
        "layout, background, text or any wording it contains; create a new ad for this concept."
        if reference_available
        else "No reference image is attached. Depict the product plainly and generically; do not invent specific "
        "product design details, logos or packaging text."
    )
    sections = [
        "You are creating ONE finished paid-social ad image for one arm of a controlled creative experiment. It must "
        "read as a real, polished ad, and it must clearly express the strategic concept below.",
        f"BRAND / PRODUCT\n{brand}",
        f"AUDIENCE\n{spec.avatar}\nAwareness stage: {spec.awareness_stage}\nFunnel stage: {spec.funnel_stage}",
        f"STRATEGIC CONCEPT\n{spec.concept_name}: {spec.messaging_angle}\nWhy this concept exists: {spec.strategic_intent}",
        f"MESSAGE TO COMMUNICATE\nThe customer concern is: {spec.customer_theme}. Express the concept above through "
        "the image and the on-image headline; the image is one execution of that idea, not a generic product shot.",
        "EXACT ON-IMAGE COPY - DO NOT REWRITE OR PARAPHRASE\n"
        f"Headline:\n{spec.on_image_headline}\n\nReproduce this text exactly as written, character for character, "
        "in legible, intentional marketing typography. Include ONLY this text in the image: no other words, "
        "numbers, logos, badges, prices or claims.",
        f"VISUAL DIRECTION\n{spec.visual_direction}",
        f"REFERENCE IMAGE GUIDANCE\n{reference}",
        "MUST PRESERVE\n" + "\n".join(f"- {c}" for c in spec.constants_preserved),
        "MUST AVOID\n" + "\n".join(f"- {c}" for c in spec.prohibited_claims),
    ]
    return "\n\n".join(sections)


def generate_ad_creative(
    spec: AdExecutionSpec,
    provider: ImageGenerationProvider,
    reference_image_path: Path | None,
    *,
    version: int = 1,
    creative_key: str = "",
    plan_fingerprint: str = "",
    batch_id: str = "",
) -> GeneratedCreative:
    """Render ONE AdExecutionSpec into a finished ad image and persist it
    (image plus a JSON sidecar holding the full spec, prompt, versioning and
    provenance) via core.assets.save_generated_asset, which never
    overwrites and never touches source_ads/. Exactly one provider call.
    The sidecar records provider/model and NEVER any credential.

    Raises ImageGenerationError for any provider or storage failure.
    """
    prompt = build_ad_prompt(spec, reference_image_path is not None, creative_context(spec.client_id))
    result = provider.generate_image(prompt, reference_image_path, size=DEFAULT_SIZE, quality=DEFAULT_QUALITY)

    generated_id = _generated_id(spec.concept_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    references = [str(reference_image_path)] if reference_image_path is not None else []
    metadata = {
        "record_type": "ad_creative_v3",
        "generated_id": generated_id,
        "client_id": spec.client_id,
        "proposal_id": spec.opportunity_id,
        "concept_id": spec.concept_id,
        "control_creative_id": spec.reference_creative_id,
        "batch_id": batch_id,
        "version": version,
        "creative_key": creative_key,
        "plan_fingerprint": plan_fingerprint,
        "ad_spec": spec.to_dict(),
        "reference_asset_paths": references,
        "provider": result.provider,
        "model": result.model,
        "generated_at": generated_at,
        "prompt": prompt,
        "revised_prompt": result.revised_prompt,
        "data_type": spec.data_type,
        "generation_source": "live",
    }
    try:
        image_path, metadata_path = save_generated_asset(
            spec.client_id, generated_id, result.image_bytes, result.output_format, metadata
        )
    except OSError as exc:
        raise ImageGenerationError(f"Could not save the generated image: {exc}")

    return GeneratedCreative(
        generated_id=generated_id,
        proposal_id=spec.opportunity_id,
        concept_id=spec.concept_id,
        control_creative_id=spec.reference_creative_id,
        client_id=spec.client_id,
        batch_id=batch_id,
        image_path=image_path,
        metadata_path=metadata_path,
        provider=result.provider,
        model=result.model,
        generated_at=generated_at,
        prompt=prompt,
        generation_source="live",
        ad_spec=spec,
        version=version,
        creative_key=creative_key,
        plan_fingerprint=plan_fingerprint,
        reference_asset_paths=references,
        data_type=spec.data_type,
    )


def _generated_id(concept_id: str) -> str:
    """A collision-safe, traceable filename stem: the version's concept id
    (already unique per proposal/batch), a compact UTC timestamp, and a
    short random suffix so two generations in the same second never
    collide.
    """
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", concept_id).strip("_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe}_{timestamp}_{uuid.uuid4().hex[:8]}"


def generate_creative(request: GenerationRequest, provider: ImageGenerationProvider) -> GeneratedCreative:
    """Render one GenerationRequest via `provider` and store the result.

    Raises ImageGenerationError for any provider failure (missing key, auth,
    timeout, refusal, malformed response) or storage failure; the caller
    (app_pages/creative_lab.py) is expected to catch this per generation
    slot, so one failure in a batch never discards another slot's success.
    """
    prompt = build_prompt(request)
    result = provider.generate_image(prompt, request.control_image_path, size=request.size, quality=request.quality)

    generated_id = _generated_id(request.concept_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "generated_id": generated_id,
        "client_id": request.client_id,
        "proposal_id": request.proposal_id,
        "concept_id": request.concept_id,
        "control_creative_id": request.control_creative_id,
        "control_image_path": str(request.control_image_path),
        "batch_id": request.batch_id,
        "on_image_headline": request.on_image_headline,
        "on_image_supporting_copy": request.on_image_supporting_copy,
        "on_image_proof": request.on_image_proof,
        "on_image_cta": request.on_image_cta,
        "provider": result.provider,
        "model": result.model,
        "generated_at": generated_at,
        "prompt": prompt,
        "revised_prompt": result.revised_prompt,
        "generation_source": "live",
    }

    try:
        image_path, metadata_path = save_generated_asset(
            request.client_id, generated_id, result.image_bytes, result.output_format, metadata
        )
    except OSError as exc:
        raise ImageGenerationError(f"Could not save the generated image: {exc}")

    return GeneratedCreative(
        generated_id=generated_id,
        proposal_id=request.proposal_id,
        concept_id=request.concept_id,
        control_creative_id=request.control_creative_id,
        client_id=request.client_id,
        batch_id=request.batch_id,
        image_path=image_path,
        metadata_path=metadata_path,
        provider=result.provider,
        model=result.model,
        generated_at=generated_at,
        prompt=prompt,
        generation_source="live",
    )


def creative_generation_mode() -> str:
    """CREATIVE_GENERATION_MODE from the environment, defaulting to
    "demo" and falling back to "demo" for any unrecognized value (never a
    silent crash over a typo'd env var). "demo" is the default so a fresh
    checkout, a rerun during development, and the actual interview all
    behave the same way unless a developer deliberately opts into "live".
    """
    mode = os.environ.get("CREATIVE_GENERATION_MODE", CREATIVE_GENERATION_MODE_DEMO).strip().lower()
    if mode not in (CREATIVE_GENERATION_MODE_DEMO, CREATIVE_GENERATION_MODE_LIVE):
        return CREATIVE_GENERATION_MODE_DEMO
    return mode


def creative_generation_ready() -> bool:
    """Whether "Generate Creatives" can proceed right now: always True in
    demo mode (no provider, no key, needed at all); in live mode, True
    only when OPENAI_API_KEY is actually set, the same gate Creative Lab
    has always shown before a live call.
    """
    if creative_generation_mode() == CREATIVE_GENERATION_MODE_LIVE:
        return bool(os.environ.get("OPENAI_API_KEY"))
    return True


def get_creative_resolver(client_id: str) -> Callable[[GenerationRequest], GeneratedCreative]:
    """The one seam where demo/live mode actually diverges: returns a
    callable(request) -> GeneratedCreative, resolved ONCE per batch
    (mirroring get_default_provider()'s own fail-fast contract, so a
    caller can fail an entire batch with one clear message instead of
    trying each slot first). Live mode returns the exact existing path
    (get_default_provider + generate_creative, unchanged); demo mode
    returns a resolver against this client's pre-generated demo asset
    manifest (agents/creative_studio/demo_assets.py), making zero
    provider calls. Both branches raise ImageGenerationError the same way
    on failure, so app_pages/creative_lab.py's error handling doesn't need
    to know which mode produced it.
    """
    if creative_generation_mode() == CREATIVE_GENERATION_MODE_LIVE:
        provider = get_default_provider()
        return lambda request: generate_creative(request, provider)

    from agents.creative_studio.demo_assets import resolve_demo_creative

    return lambda request: resolve_demo_creative(client_id, request)
