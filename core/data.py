"""Client-scoped data loading for the Brio-style demo datasets.

This module only loads and joins: it does not calculate or interpret.
Loading = reading data/<client_id>/*.csv as-is. Calculating (KPIs,
aggregations, comparisons) lives in core/analytics.py. Interpreting
(what a pattern means) is an AI agent's job, later.

No Streamlit dependency, so this is reusable outside a running app.
"""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _client_dir(client_id: str) -> Path:
    return DATA_DIR / client_id


def load_creative_catalog(client_id: str) -> pd.DataFrame:
    """One row per creative: campaign, funnel stage, product, and messaging attributes."""
    return pd.read_csv(_client_dir(client_id) / "creative_catalog.csv")


def load_meta_ads(client_id: str) -> pd.DataFrame:
    """Daily Meta performance rows, keyed by date + creative_id."""
    df = pd.read_csv(_client_dir(client_id) / "meta_ads.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_customer_signals(client_id: str) -> pd.DataFrame:
    """Individual customer signals (Reddit, reviews, CRM notes, social, search)."""
    df = pd.read_csv(_client_dir(client_id) / "customer_signals.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_performance_with_creatives(client_id: str) -> pd.DataFrame:
    """Meta performance joined to the creative's catalog attributes.

    Joins on creative_id. campaign_id is taken from meta_ads (the
    performance record) rather than the catalog, since the catalog's
    client_id/campaign_id/data_type would otherwise collide with meta's
    own columns of the same name.
    """
    meta = load_meta_ads(client_id)
    catalog = load_creative_catalog(client_id)
    catalog_attrs = catalog.drop(columns=["client_id", "campaign_id", "data_type"])
    return meta.merge(catalog_attrs, on="creative_id", how="left", validate="many_to_one")


def has_observed_ad_copy(client_id: str, creative_id: str) -> bool:
    """Whether this creative's ad-level copy came from real, collected
    Meta Ads Library data (data/<client>/observed_ad_copy.csv), as opposed
    to the catalog's own synthetic fallback copy. A read-only provenance
    check, shared by app_pages/experiments.py and app_pages/creative_lab.py
    (previously duplicated in experiments.py alone): never changes which
    copy build_control_ad_package already chose.
    """
    path = _client_dir(client_id) / "observed_ad_copy.csv"
    if not path.exists():
        return False
    return creative_id in pd.read_csv(path)["creative_id"].values


def creative_image_provenance(client_id: str, creative_id: str) -> str:
    """Whether this creative's own IMAGE traces to a real, independently
    observed public ad (creative_catalog's own creative_origin ==
    "public_ad_inspired") or is purely demo-synthetic. Distinct from
    has_observed_ad_copy above: one is about the ad-level TEXT, this one
    about the source image, since a creative can differ on either axis.
    Shared by app_pages/experiments.py and app_pages/creative_lab.py
    (previously private to experiments.py alone).
    """
    catalog = load_creative_catalog(client_id)
    row = catalog.loc[catalog["creative_id"] == creative_id]
    if not row.empty and row.iloc[0].get("creative_origin") == "public_ad_inspired":
        return "Public-ad-observed source creative"
    return "Demo synthetic source creative"
