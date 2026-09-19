"""Pre-generated demo asset resolution: Creative Studio's "demo"
generation mode (agents/creative_studio/generation.py::
get_creative_resolver, CREATIVE_GENERATION_MODE). Turns a GenerationRequest
into a GeneratedCreative by looking up an EXISTING, already-generated image
under assets/<client_id>/generated/, instead of calling a live image
provider, so a demo (or ordinary local development) never waits on, or
pays for, a real API call.

Isolated demo-fixture logic: this module never invents an image, never
substitutes one creative's saved asset for a different one, and never
tells a caller a live provider call happened when it didn't.
generated_id/provider/model/generated_at/prompt on a resolved
GeneratedCreative always describe the REAL historical generation event
that actually produced those pixels (read back from that asset's own
metadata JSON, written at the time it was really generated); only
generation_source ("pre_generated_demo") marks that resolving it just now
made no call at all. The user-facing "AI-generated demo creatives"
language elsewhere is still accurate: these images really were AI
generated, once, for real.

The manifest (assets/<client_id>/generated/demo_manifest.json) is a small,
deterministic INDEX, not a copy of the metadata: each entry names which
existing generated_id is the canonical asset for one (proposal, batch,
creative slot), and resolution always re-reads that asset's own real
metadata.json as the actual source of truth, cross-checking it against the
manifest entry and the live request before ever handing back a path. A
manifest entry pointing at a missing file, a metadata mismatch, or no
entry at all all resolve the same way: ImageGenerationError, "this
fixture is unavailable," never a guess and never silently reusing a
different creative's image.

build_demo_manifest()/rebuild_demo_manifest() (bottom of this module) are
the one supported way to add or refresh entries: they scan every real
metadata.json already under assets/<client_id>/generated/, so the
manifest can never claim an asset that doesn't actually exist. Run after
manually generating and saving a new batch (see this milestone's own
report for exactly when that's needed); never invoked automatically by
the app itself.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from agents.creative_studio.generation import GeneratedCreative, GenerationRequest
from agents.creative_studio.image_provider import ImageGenerationError
from core.assets import generated_assets_dir
from core.data import load_creative_catalog

GENERATION_SOURCE_DEMO = "pre_generated_demo"
MANIFEST_FILENAME = "demo_manifest.json"
_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "webp")


def _manifest_path(client_id: str) -> Path:
    return generated_assets_dir(client_id) / MANIFEST_FILENAME


def load_demo_manifest(client_id: str) -> list[dict]:
    """This client's demo-fixture index, one entry per (proposal, batch,
    creative slot). Returns an empty list (never raises) if the manifest
    doesn't exist yet, the same "nothing to show, not an error" convention
    core/assets.py already uses for a client with no optional file.
    """
    path = _manifest_path(client_id)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return payload.get("entries", [])


def _entry_matches_request(entry: dict, request: GenerationRequest) -> bool:
    """The manifest entry's own recorded facts must match the LIVE
    request currently being resolved: proposal, control creative, product,
    funnel stage, and the exact creative slot (concept_id). Any mismatch
    means this entry is not a safe match for this request, full stop; no
    partial-credit fuzzy matching.
    """
    return (
        entry.get("proposal_id") == request.proposal_id
        and entry.get("control_creative_id") == request.control_creative_id
        and entry.get("product") == request.product
        and entry.get("funnel_stage") == request.funnel_stage
        and entry.get("concept_id") == request.concept_id
    )


def _find_image_path(directory: Path, generated_id: str) -> Path | None:
    for ext in _IMAGE_EXTENSIONS:
        candidate = directory / f"{generated_id}.{ext}"
        if candidate.exists():
            return candidate
    return None


def resolve_demo_creative(client_id: str, request: GenerationRequest) -> GeneratedCreative:
    """The demo-mode counterpart to generation.py::generate_creative: same
    signature shape (a GenerationRequest in, a GeneratedCreative out,
    ImageGenerationError on failure), zero provider calls. Validates in
    three independent steps, any of which can fail the resolution safely
    rather than guessing:

    1. A manifest entry exists whose own recorded proposal/control
       creative/product/funnel stage/concept_id all match this request
       exactly.
    2. That entry's generated_id actually has both an image file and a
       metadata.json still on disk (a manifest can go stale if files are
       ever moved or removed outside this module).
    3. The metadata.json's OWN fields agree with both the manifest entry
       and the live request (defense in depth: the manifest is an index,
       the metadata file is the real record, and the two are expected to
       agree).
    """
    directory = generated_assets_dir(client_id)
    matches = [e for e in load_demo_manifest(client_id) if _entry_matches_request(e, request)]
    if not matches:
        raise ImageGenerationError(
            f"No pre-generated demo asset is available for this creative version yet "
            f"({request.concept_id}). Generate and save it first, or set "
            f'CREATIVE_GENERATION_MODE="live".'
        )

    entry = matches[0]
    generated_id = entry.get("generated_id", "")
    metadata_path = directory / f"{generated_id}.json"
    if not generated_id or not metadata_path.exists():
        raise ImageGenerationError(
            f"The demo fixture for {request.concept_id} is listed in the manifest but its metadata file is "
            f"missing ({generated_id or 'no generated_id recorded'})."
        )
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError):
        raise ImageGenerationError(f"The demo fixture metadata for {generated_id} could not be read.")

    if (
        metadata.get("proposal_id") != request.proposal_id
        or metadata.get("concept_id") != request.concept_id
        or metadata.get("control_creative_id") != request.control_creative_id
    ):
        raise ImageGenerationError(
            f"The demo fixture metadata for {generated_id} does not match this creative version "
            f"({request.concept_id}); refusing to use it rather than guessing."
        )

    image_path = _find_image_path(directory, generated_id)
    if image_path is None:
        raise ImageGenerationError(f"The demo fixture image file for {generated_id} is missing.")

    return GeneratedCreative(
        generated_id=generated_id,
        proposal_id=metadata["proposal_id"],
        concept_id=metadata["concept_id"],
        control_creative_id=metadata["control_creative_id"],
        client_id=client_id,
        batch_id=metadata.get("batch_id", request.batch_id),
        image_path=image_path,
        metadata_path=metadata_path,
        provider=metadata.get("provider", "unknown"),
        model=metadata.get("model", ""),
        generated_at=metadata.get("generated_at", ""),
        prompt=metadata.get("prompt", ""),
        generation_source=GENERATION_SOURCE_DEMO,
    )


@dataclass
class ManifestBuildReport:
    """What build_demo_manifest actually did: how many real metadata
    files it found, how many became manifest entries (one per unique
    concept_id; a concept_id with more than one real generation on disk
    keeps only the earliest by generated_at, noted in duplicate_concept_ids
    so a human can see a spare copy exists), and any metadata file it had
    to skip because it lacked a usable product/funnel-stage lookup.
    """

    client_id: str
    metadata_files_scanned: int
    entries_written: int
    duplicate_concept_ids: list[str]
    skipped_generated_ids: list[str]


def rebuild_demo_manifest(client_id: str) -> ManifestBuildReport:
    """Scan every real metadata.json under assets/<client_id>/generated/
    and (re)write demo_manifest.json from scratch: the manifest is always
    a derived index of what's actually on disk, never hand-maintained
    separately from it, so it can never claim an asset that doesn't exist.

    One entry per unique concept_id (the earliest real generation, by its
    own generated_at, is kept as canonical when more than one exists for
    the same slot); product/funnel_stage are looked up from this client's
    own creative_catalog.csv via each entry's control_creative_id, never
    guessed. A metadata file with no control_creative_id, or one not found
    in the catalog, is skipped and reported rather than written with a
    blank/incorrect product or funnel stage.

    Not called by the app itself: run by hand after manually generating
    and saving a new batch of demo assets (see this milestone's report for
    when that's needed), so the manifest never silently changes underneath
    a running demo session.
    """
    directory = generated_assets_dir(client_id)
    catalog = load_creative_catalog(client_id)

    best_by_concept: dict[str, dict] = {}
    duplicate_concept_ids: list[str] = []
    skipped_generated_ids: list[str] = []
    metadata_files = sorted(directory.glob("*.json"))
    metadata_files = [p for p in metadata_files if p.name != MANIFEST_FILENAME]

    for metadata_path in metadata_files:
        try:
            metadata = json.loads(metadata_path.read_text())
        except (OSError, json.JSONDecodeError):
            skipped_generated_ids.append(metadata_path.stem)
            continue

        concept_id = metadata.get("concept_id")
        control_creative_id = metadata.get("control_creative_id")
        proposal_id = metadata.get("proposal_id")
        generated_id = metadata.get("generated_id", metadata_path.stem)
        if not concept_id or not control_creative_id or not proposal_id:
            skipped_generated_ids.append(generated_id)
            continue

        catalog_row = catalog.loc[catalog["creative_id"] == control_creative_id]
        if catalog_row.empty:
            skipped_generated_ids.append(generated_id)
            continue

        # A metadata.json can outlive its own image file (e.g. the image
        # was removed some other way after being generated); never make
        # that generated_id canonical, since resolve_demo_creative would
        # then point a "successful" slot at a file that doesn't exist.
        if _find_image_path(directory, generated_id) is None:
            skipped_generated_ids.append(generated_id)
            continue

        batch_id = metadata.get("batch_id", "")
        batch_index = int(batch_id.replace("batch", "")) if batch_id.startswith("batch") else None

        candidate = {
            "proposal_id": proposal_id,
            "control_creative_id": control_creative_id,
            "product": catalog_row.iloc[0]["product_name"],
            "funnel_stage": catalog_row.iloc[0]["funnel_stage"],
            "batch_index": batch_index,
            "concept_id": concept_id,
            "generated_id": generated_id,
            "generation_source": GENERATION_SOURCE_DEMO,
        }

        existing = best_by_concept.get(concept_id)
        if existing is None:
            best_by_concept[concept_id] = candidate
        else:
            duplicate_concept_ids.append(concept_id)
            existing_generated_at = json.loads((directory / f"{existing['generated_id']}.json").read_text()).get("generated_at", "")
            if metadata.get("generated_at", "") < existing_generated_at:
                best_by_concept[concept_id] = candidate

    manifest = {"client_id": client_id, "entries": list(best_by_concept.values())}
    _manifest_path(client_id).write_text(json.dumps(manifest, indent=2))

    return ManifestBuildReport(
        client_id=client_id,
        metadata_files_scanned=len(metadata_files),
        entries_written=len(best_by_concept),
        duplicate_concept_ids=sorted(set(duplicate_concept_ids)),
        skipped_generated_ids=skipped_generated_ids,
    )
