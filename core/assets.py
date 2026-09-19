"""Creative asset resolution: mapping a creative_id to its source-ad image,
and storage for AI-generated creative assets.

Images under assets/<client_id>/source_ads/ are cropped screenshots of
publicly visible ad creative. Filenames stay human-readable (e.g.
brio_q60.png) rather than being renamed to a creative_id, so the mapping
from creative_id to filename lives in a small lookup table,
assets/<client_id>/source_ads/asset_mapping.csv, instead.

Not every creative_id has an image, most don't. That's expected: this
module returns None for a creative_id with no mapping entry, or whose
mapped file is missing on disk. It never substitutes a placeholder image,
so a caller can't accidentally present a stand-in as real ad evidence.

Important distinction this module exists to protect: an image resolved
here is creative evidence (a real, publicly visible Brio ad). The
performance numbers attached to the same creative_id in
data/<client_id>/meta_ads.csv are synthetic demo data. The two must never
be presented together as if the image caused those specific numbers.

A second, equally important distinction: assets/<client_id>/generated/ is
never source_ads/. A generated image is AI output from Creative Studio's
live image-generation step (agents/creative_studio/), not real ad evidence,
and the two directories must never mix so a caller can't accidentally
present a generated demo image as a real Brio ad, or overwrite a real
source ad with generated output.
"""
import json
from pathlib import Path

import pandas as pd

from core.data import load_creative_catalog

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
GENERATED_SUBDIR = "generated"


def _source_ads_dir(client_id: str) -> Path:
    return ASSETS_DIR / client_id / "source_ads"


def _mapping_path(client_id: str) -> Path:
    return _source_ads_dir(client_id) / "asset_mapping.csv"


def load_asset_mapping(client_id: str) -> pd.DataFrame:
    """The raw creative_id -> filename lookup table for a client.

    Returns an empty (but correctly shaped) DataFrame if the client has no
    asset_mapping.csv yet, rather than raising.
    """
    path = _mapping_path(client_id)
    if not path.exists():
        return pd.DataFrame(columns=["creative_id", "asset_file"])
    return pd.read_csv(path)


def resolve_creative_image(client_id: str, creative_id: str) -> Path | None:
    """Return the source-ad image path for a creative_id, or None.

    None means "no evidence image for this creative": either it was never
    mapped, or the mapped file isn't on disk. Callers should treat None as
    "nothing to show," not as an error.
    """
    mapping = load_asset_mapping(client_id)
    if "creative_id" not in mapping.columns:
        return None

    match = mapping.loc[mapping["creative_id"] == creative_id, "asset_file"]
    if match.empty:
        return None

    image_path = _source_ads_dir(client_id) / match.iloc[0]
    if not image_path.exists():
        return None
    return image_path


def resolve_image_for_product(client_id: str, product_name: str) -> tuple[str, Path] | None:
    """The first mapped source-ad image belonging to a given product, or None.

    For a caller that has a product (e.g. an insight about a product overall)
    rather than a specific creative_id. Returns (creative_id, image_path) for
    the first catalog creative of that product with a resolvable image, in
    catalog order. There's no "best" ordering to apply here, since this
    module doesn't interpret performance.
    """
    catalog = load_creative_catalog(client_id)
    creative_ids = catalog.loc[catalog["product_name"] == product_name, "creative_id"]
    for creative_id in creative_ids:
        image_path = resolve_creative_image(client_id, creative_id)
        if image_path is not None:
            return creative_id, image_path
    return None


def generated_assets_dir(client_id: str) -> Path:
    """This client's AI-generated creative asset directory, created if
    needed. Always assets/<client_id>/generated/, never source_ads/: see
    the module docstring for why the two must never mix.
    """
    directory = ASSETS_DIR / client_id / GENERATED_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_generated_asset(
    client_id: str, generated_id: str, image_bytes: bytes, output_format: str, metadata: dict
) -> tuple[Path, Path]:
    """Write one generated image and a JSON metadata sidecar, both named
    after generated_id so a caller can supply any collision-safe id (see
    agents/creative_studio/generation.py) without this module needing to
    invent uniqueness itself. Raises FileExistsError rather than silently
    overwriting if generated_id was somehow already used. Returns
    (image_path, metadata_path).
    """
    directory = generated_assets_dir(client_id)
    image_path = directory / f"{generated_id}.{output_format}"
    if image_path.exists():
        raise FileExistsError(f"Generated asset already exists: {image_path}")
    image_path.write_bytes(image_bytes)
    metadata_path = directory / f"{generated_id}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str))
    return image_path, metadata_path


def generated_asset_exists(image_path) -> bool:
    """Whether a previously generated creative's image file is still on
    disk and readable.

    A generated image's path is captured once, at generation time, into a
    Creative Lab slot or an experiment_handoff, and never re-verified
    afterward. Nothing stops the underlying file from disappearing later
    (manual cleanup of assets/<client_id>/generated/, a moved or rebuilt
    assets folder) without that stored state knowing: the path is just a
    string/Path, not a live reference. Every place that renders a
    generated image from a stored path (Creative Lab's gallery and "View
    larger," the Experiments treatment gallery and its own "View larger")
    must call this immediately before st.image, since a missing file
    raises MediaFileStorageError, not a catchable "not found" value; the
    check has to happen before that call, not around it. Accepts a Path,
    a str, or None/""/falsy (treated as missing, never an error).
    """
    if not image_path:
        return False
    try:
        return Path(image_path).is_file()
    except OSError:
        return False
