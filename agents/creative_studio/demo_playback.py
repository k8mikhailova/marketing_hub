"""Demo playback (Milestone 28): a deterministic, zero-provider-call way to
replay the SIX real creatives already produced by a successful
CREATIVE_GENERATION_MODE=live run, for a reliable interview demo.

HARD GUARANTEE: this module never imports agents.creative_studio.pipeline
or text_provider (the only two modules that ever construct a text/image
provider), never calls a provider method, and never constructs an OpenAI
client. It does import generation.py, but ONLY for the shared
GeneratedCreative dataclass (Milestone 27's own design: live, saved, and
demo playback must resolve into the SAME representation); image_provider.py
is therefore reachable in this module's import graph, but only as an
unused, transitive dependency of that import, since image_provider.py
itself imports the openai package lazily, inside OpenAIImageProvider.
__init__, never at module load. Reading the sidecar JSON for an
already-generated creative is the only kind of "generation" this module can
do; this is verified at runtime in tests by patching openai.OpenAI to raise
if constructed at all while exercising every function in this module.

Identity is explicit (assets/<client>/demo_playback_manifest.json), not
"whatever the newest matching file on disk happens to be": each entry maps
one concept_id to the specific generated_id/version/plan_fingerprint chosen
for the demo. The manifest references existing files by id; it duplicates no
image bytes and holds no credential.

resolve_playback_creative re-derives the GeneratedCreative from the SAME
sidecar JSON creative_store.load_saved_creatives reads, so a played-back
creative is byte-for-byte the object a live run would have produced, with
generation_source="demo_playback" as the only marker of how it was reached
just now; provider/model/generated_at/prompt stay the REAL values from the
original generation.
"""
import json
from pathlib import Path

import core.assets as assets
from agents.creative_studio.creative_store import RECORD_TYPE, _IMAGE_EXTENSIONS
from agents.creative_studio.execution import AdExecutionSpec
from agents.creative_studio.generation import GeneratedCreative

MANIFEST_FILENAME = "demo_playback_manifest.json"


class DemoPlaybackUnavailable(Exception):
    """A concept has no manifest entry, or its recorded asset is missing or
    no longer matches the current strategy/concept. Never falls back to a
    live call, a different concept's asset, or fabricated copy; the message
    is safe to show a marketer directly and names the concept."""


def _manifest_path(client_id: str) -> Path:
    return assets.ASSETS_DIR / client_id / MANIFEST_FILENAME


def load_manifest(client_id: str) -> dict:
    """{concept_id: {generated_id, proposal_id, version, plan_fingerprint}},
    or {} if no manifest exists yet. Malformed JSON degrades to {} rather
    than raising, so a broken manifest fails each concept individually
    (via resolve_playback_creative) instead of crashing the page."""
    path = _manifest_path(client_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("concepts", {}) if isinstance(data, dict) else {}


def resolve_playback_creative(client_id: str, concept_id: str, expected_fingerprint: str) -> GeneratedCreative:
    """The exact saved GeneratedCreative recorded for `concept_id`, read
    straight from disk (no directory scan: the manifest names the file).
    Raises DemoPlaybackUnavailable, never a live call or a substitution, if:
    the concept has no manifest entry; its metadata or image file is
    missing; its metadata disagrees with the manifest entry; or the
    strategy fingerprint no longer matches (the plan changed since this demo
    asset was recorded).
    """
    entry = load_manifest(client_id).get(concept_id)
    if not entry:
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: no demo playback entry for {concept_id}.")

    generated_id = entry.get("generated_id", "")
    directory = assets.generated_assets_dir(client_id)
    metadata_path = directory / f"{generated_id}.json"
    if not generated_id or not metadata_path.exists():
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: metadata for {concept_id} is missing.")
    try:
        data = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError):
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: metadata for {concept_id} could not be read.")

    if data.get("record_type") != RECORD_TYPE or data.get("concept_id") != concept_id:
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: recorded asset no longer matches {concept_id}.")
    if expected_fingerprint and data.get("plan_fingerprint") != expected_fingerprint:
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: strategy has changed since this demo asset was recorded ({concept_id}).")
    if not isinstance(data.get("ad_spec"), dict):
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: no structured ad data for {concept_id}.")

    image_path = None
    for ext in _IMAGE_EXTENSIONS:
        candidate = directory / f"{generated_id}.{ext}"
        if candidate.is_file():
            image_path = candidate
            break
    if image_path is None:
        raise DemoPlaybackUnavailable(f"Saved demo creative unavailable: image file for {concept_id} is missing.")

    return GeneratedCreative(
        generated_id=generated_id,
        proposal_id=data.get("proposal_id", ""),
        concept_id=concept_id,
        control_creative_id=data.get("control_creative_id", ""),
        client_id=client_id,
        batch_id=data.get("batch_id", ""),
        image_path=image_path,
        metadata_path=metadata_path,
        provider=data.get("provider", ""),
        model=data.get("model", ""),
        generated_at=data.get("generated_at", ""),
        prompt=data.get("prompt", ""),
        generation_source="demo_playback",
        ad_spec=AdExecutionSpec.from_dict(data["ad_spec"]),
        version=int(data.get("version", 1)),
        creative_key=data.get("creative_key", ""),
        plan_fingerprint=data.get("plan_fingerprint", ""),
        reference_asset_paths=list(data.get("reference_asset_paths", [])),
        data_type=data.get("data_type", ""),
    )
