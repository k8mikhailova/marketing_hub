"""Persistence and identity for finished ad creatives (Milestone 27).

A finished creative is stored exactly where every generated asset already
lives (assets/<client>/generated/, via core.assets.save_generated_asset): the
image plus a JSON sidecar. This module owns only the READ side and the
identity rules:

- plan_fingerprint: a hash of the strategic fields a creative was built from
  (pain point, product, funnel stage, angle, intent, learning question,
  constants, reference creative). A saved creative is only ever shown for a
  concept whose fingerprint still matches, so a changed plan can never
  present a stale ad as if it belonged to the new strategy.
- creative_key: the fingerprint plus the text and image model ids. Asking for
  a creative whose key already exists on disk returns the saved one WITHOUT
  any provider call: this is the duplicate-call protection that survives
  Streamlit reruns and app restarts. Regenerate is the one deliberate way
  around it and always writes a NEW version.
- versions: every generation is a new file (ids are unique), never an
  overwrite; version numbers increase per concept. Older versions stay on
  disk and in the returned list.

Live and demo mode both resolve into the same GeneratedCreative: whatever a
live run saved is what demo mode (no provider, no key) later loads, with
generation_source "saved". Old-flow sidecars (no record_type) are ignored.

This module imports core.assets as a module (not from-imports) so tests can
redirect the generated-assets directory.
"""
import hashlib
import json
from pathlib import Path

import core.assets as assets
from agents.creative_studio.execution import AdExecutionSpec, learning_question_for
from agents.creative_studio.generation import GeneratedCreative
from agents.creative_studio.engine import CreativeConcept
from agents.strategist.engine import CreativeOpportunity

RECORD_TYPE = "ad_creative_v3"
_IMAGE_EXTENSIONS = ("png", "jpeg", "jpg", "webp")


def plan_fingerprint(opportunity: CreativeOpportunity, concept: CreativeConcept) -> str:
    payload = {
        "pain_point": opportunity.pain_point,
        "product": opportunity.product,
        "funnel_stage": opportunity.funnel_stage,
        "avatar": opportunity.avatar,
        "learning_question": learning_question_for(opportunity),
        "variable": opportunity.variable_to_test,
        "constants": list(opportunity.constants_to_preserve),
        "control": opportunity.control_creative_id,
        "concept_id": concept.concept_id,
        "angle": concept.angle,
        "intent": concept.why_this_concept_exists,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def creative_key(client_id: str, concept_id: str, fingerprint: str, text_model: str, image_model: str) -> str:
    raw = "|".join([client_id, concept_id, fingerprint, text_model, image_model])
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _image_for(directory: Path, generated_id: str) -> Path | None:
    for ext in _IMAGE_EXTENSIONS:
        candidate = directory / f"{generated_id}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def load_saved_creatives(client_id: str, concept_id: str, fingerprint: str) -> list[GeneratedCreative]:
    """Every saved version of this concept's finished creative whose strategy
    fingerprint still matches, oldest first. Disk reads only; never a
    provider call. A sidecar whose image is missing or whose JSON is
    unreadable is skipped rather than raising."""
    directory = assets.generated_assets_dir(client_id)
    found: list[GeneratedCreative] = []
    for meta_path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("record_type") != RECORD_TYPE:
            continue
        if data.get("concept_id") != concept_id or data.get("plan_fingerprint") != fingerprint:
            continue
        image_path = _image_for(directory, data.get("generated_id", ""))
        if image_path is None or not isinstance(data.get("ad_spec"), dict):
            continue
        found.append(
            GeneratedCreative(
                generated_id=data["generated_id"],
                proposal_id=data.get("proposal_id", ""),
                concept_id=concept_id,
                control_creative_id=data.get("control_creative_id", ""),
                client_id=client_id,
                batch_id=data.get("batch_id", ""),
                image_path=image_path,
                metadata_path=meta_path,
                provider=data.get("provider", ""),
                model=data.get("model", ""),
                generated_at=data.get("generated_at", ""),
                prompt=data.get("prompt", ""),
                generation_source="saved",
                ad_spec=AdExecutionSpec.from_dict(data["ad_spec"]),
                version=int(data.get("version", 1)),
                creative_key=data.get("creative_key", ""),
                plan_fingerprint=fingerprint,
                reference_asset_paths=list(data.get("reference_asset_paths", [])),
                data_type=data.get("data_type", ""),
            )
        )
    return sorted(found, key=lambda c: (c.version, c.generated_at))


def next_version(existing: list[GeneratedCreative]) -> int:
    return max((c.version for c in existing), default=0) + 1
