"""Creative Studio V3 pipeline (Milestone 27): one Creative Concept in, one
FINISHED, persisted ad out.

    CreativeConcept -> AdExecutionSpec (text step) -> image request
                    -> GeneratedCreative (image step) -> saved to disk

Two provider calls per concept at most (one text, one image), each behind a
narrow interface (execution.TextGenerationProvider,
image_provider.ImageGenerationProvider), so nothing above this module knows
OpenAI exists. Creative Lab supplies the human decision to generate; this
module never decides to spend money on its own.

Duplicate-call protection lives here and in creative_store:
- an existing saved creative with the same creative_key is RETURNED with no
  provider call at all (survives reruns and restarts);
- force=True (the explicit Regenerate action) is the only way around that,
  and always writes a NEW version instead of replacing the old one;
- the validated spec is handed to the caller through `on_spec` the moment it
  exists, so a failure in the IMAGE step can be retried without paying for
  the text step again.

Reference-image strategy (see reference_for): the opportunity's own existing
same-product ad is the default PRODUCT/brand reference, passed for
appearance only (the prompt forbids reproducing its layout or wording); if
it has no source image the product's first mapped image is used; if there is
none, generation proceeds WITHOUT a reference and the record says so. It is
not forced where none exists, and source assets are only ever read.
"""
from pathlib import Path
from typing import Callable

import agents.creative_studio.config as config
from agents.creative_studio.creative_store import (
    creative_key,
    load_saved_creatives,
    next_version,
    plan_fingerprint,
)
from agents.creative_studio.engine import CreativeConcept
from agents.creative_studio.execution import AdExecutionSpec, generate_execution_spec
from agents.creative_studio.generation import GeneratedCreative, generate_ad_creative
from agents.creative_studio.image_provider import ImageGenerationError, get_default_provider
from agents.creative_studio.text_provider import get_text_provider
from agents.strategist.engine import CreativeOpportunity
from core.assets import resolve_creative_image, resolve_image_for_product


def reference_for(client_id: str, opportunity: CreativeOpportunity) -> Path | None:
    path = resolve_creative_image(client_id, opportunity.control_creative_id)
    if path is not None:
        return path
    fallback = resolve_image_for_product(client_id, opportunity.product)
    return fallback[1] if fallback else None


def saved_versions(client_id: str, opportunity: CreativeOpportunity, concept: CreativeConcept) -> list[GeneratedCreative]:
    return load_saved_creatives(client_id, concept.concept_id, plan_fingerprint(opportunity, concept))


def produce_creative(
    client_id: str,
    opportunity: CreativeOpportunity,
    concept: CreativeConcept,
    siblings: list[CreativeConcept],
    text_provider,
    image_provider,
    *,
    performance_context: str = "",
    spec: AdExecutionSpec | None = None,
    accepted_specs: list[AdExecutionSpec] | None = None,
    force: bool = False,
    on_spec: Callable[[AdExecutionSpec], None] | None = None,
) -> GeneratedCreative:
    """Produce (or, unless force, reuse) the finished creative for one
    concept. Raises ExecutionSpecError / TextGenerationError /
    ImageGenerationError for the corresponding failures; nothing is saved
    on failure, and previously saved versions are never touched."""
    fingerprint = plan_fingerprint(opportunity, concept)
    text_model = getattr(text_provider, "model", config.text_model()) if text_provider is not None else config.text_model()
    key = creative_key(client_id, concept.concept_id, fingerprint, text_model, config.image_model())
    existing = load_saved_creatives(client_id, concept.concept_id, fingerprint)
    if not force:
        for saved in existing:
            if saved.creative_key == key:
                return saved

    if spec is None:
        spec = generate_execution_spec(
            client_id, opportunity, concept, siblings, text_provider, performance_context, accepted_specs
        )
    if on_spec is not None:
        on_spec(spec)

    return generate_ad_creative(
        spec,
        image_provider,
        reference_for(client_id, opportunity),
        version=next_version(existing),
        creative_key=key,
        plan_fingerprint=fingerprint,
    )


def get_providers():
    """(text provider, image provider), resolved once per generation action.
    Either raises (TextGenerationError / ImageGenerationError) BEFORE any
    network call if OPENAI_API_KEY is missing."""
    return get_text_provider(), get_default_provider()


__all__ = ["ImageGenerationError", "get_providers", "produce_creative", "reference_for", "saved_versions"]
