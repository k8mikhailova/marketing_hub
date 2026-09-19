"""Explicit, auditable mapping between customer-signal themes and creative
messaging, and the calculations that measure how well current creative
covers each theme.

This is the one place that connects a customer-signal theme
(customer_signals.csv: demo_theme_label) to the literal keywords used to
detect that theme in creative copy (creative_catalog.csv: headline,
primary_text). No ad hoc keyword checks belong anywhere else, including in
the Intelligence Agent's evidence-building code (agents/intelligence/) or
Overview's preview cards (core/insights.py): both import from here, so
there is exactly one definition of "does this creative address this theme."

A creative counts as leading with (the primary hook for) a theme if a
keyword appears in its headline, mentioning it if a keyword appears only in
the supporting body copy, and absent if neither field contains a keyword.
This is deliberately simple substring matching, not NLP: it will miss a
theme expressed without these literal words (e.g. an ad that implies
convenience without the word "easy"), a known limitation of a small,
explicit, auditable taxonomy over a fuzzy classifier.
"""
import pandas as pd

from core.analytics import theme_associated_products

CUSTOMER_THEME_TO_CREATIVE_KEYWORDS: dict[str, list[str]] = {
    "Taste & odor": ["taste", "tasting", "odor", "smell"],
    "Trust & water quality": ["trust", "quality", "contaminant", "purity", "pure"],
    "Bottled water frustration": ["bottled water", "plastic bottle", "single-use"],
    "Family & health reassurance": ["family", "health", "safe", "safety", "kids", "reassur"],
    "Installation & setup": ["install", "setup", "undersink", "tankless"],
    "Convenience & routine": ["convenien", "routine", "easy", "easier", "ritual"],
    "Technical filtration": ["filtration", "filter", "reverse osmosis"],
    "Cost & value": ["save", "saving", "price", "afford", "value", "limited-time"],
}


def classify_theme_emphasis(catalog: pd.DataFrame, theme: str, products: list[str] | None = None) -> pd.DataFrame:
    """Tag each relevant creative as primary_hook, mentioned, or absent for `theme`.

    `products`, when given, scopes "relevant" to those products' creatives;
    None checks the whole catalog. Raises KeyError for a theme not in
    CUSTOMER_THEME_TO_CREATIVE_KEYWORDS rather than silently returning an
    empty, misleading classification.
    """
    keywords = CUSTOMER_THEME_TO_CREATIVE_KEYWORDS[theme]
    relevant = catalog if products is None else catalog[catalog["product_name"].isin(products)]
    relevant = relevant.copy()
    headline_hit = relevant["headline"].str.lower().apply(lambda t: any(kw in t for kw in keywords))
    body_hit = relevant["primary_text"].str.lower().apply(lambda t: any(kw in t for kw in keywords))
    relevant["emphasis"] = "absent"
    relevant.loc[body_hit & ~headline_hit, "emphasis"] = "mentioned"
    relevant.loc[headline_hit, "emphasis"] = "primary_hook"
    return relevant[["creative_id", "product_name", "funnel_stage", "headline", "emphasis"]]


def creative_coverage(catalog: pd.DataFrame, theme: str, products: list[str] | None = None) -> dict:
    """Coverage summary for one theme: counts, ratio, and distributions.

    See classify_theme_emphasis for how "relevant," "primary_hook," and
    "mentioned" are determined. Distributions describe the relevant set
    itself (e.g. how many of the relevant creatives are TOF vs MOF vs BOF),
    not just the creatives that mention the theme.
    """
    classified = classify_theme_emphasis(catalog, theme, products)
    counts = classified["emphasis"].value_counts()
    total = len(classified)
    primary_hook = int(counts.get("primary_hook", 0))
    mentioned = int(counts.get("mentioned", 0))
    absent = int(counts.get("absent", 0))
    return {
        "theme": theme,
        "products": sorted(classified["product_name"].unique().tolist()),
        "relevant_creatives": total,
        "primary_hook_count": primary_hook,
        "mentioned_count": mentioned,
        "absent_count": absent,
        "primary_hook_ratio": (primary_hook / total) if total else 0.0,
        "funnel_stage_distribution": classified["funnel_stage"].value_counts().to_dict(),
        "product_distribution": classified["product_name"].value_counts().to_dict(),
        "creative_ids": {
            "primary_hook": classified.loc[classified["emphasis"] == "primary_hook", "creative_id"].tolist(),
            "mentioned": classified.loc[classified["emphasis"] == "mentioned", "creative_id"].tolist(),
            "absent": classified.loc[classified["emphasis"] == "absent", "creative_id"].tolist(),
        },
    }


def theme_coverage_landscape(
    signals: pd.DataFrame,
    catalog: pd.DataFrame,
    product: str | None = None,
    theme_col: str = "demo_theme_label",
    product_col: str = "product_context",
) -> pd.DataFrame:
    """One row per theme: how much customers discuss it (signal_share) and
    how much current creative leads with it (primary_hook_ratio), so the
    two can be compared directly.

    When `product` is given, both sides are scoped to that single product
    (signals mentioning it, creatives for it), an apples-to-apples view of
    one product's conversation versus its own creative. When `product` is
    None, each theme uses its own associated products
    (core.analytics.theme_associated_products), since different themes
    naturally relate to different products, and signal_share is out of all
    signals, matching the convention used everywhere else in this app.
    """
    scoped_signals = signals if product is None else signals[signals[product_col] == product]
    total = len(scoped_signals)
    catalog_products = set(catalog["product_name"].unique())

    rows = []
    for theme in CUSTOMER_THEME_TO_CREATIVE_KEYWORDS:
        theme_signals = scoped_signals[scoped_signals[theme_col] == theme]
        signal_count = len(theme_signals)
        if signal_count == 0:
            continue

        if product is not None:
            products = [product] if product in catalog_products else []
        else:
            assoc = theme_associated_products(signals, theme)
            products = [p for p in assoc[product_col] if p in catalog_products]
        if not products:
            continue

        coverage = creative_coverage(catalog, theme, products=products)
        rows.append(
            {
                "theme": theme,
                "signal_count": signal_count,
                "signal_share": (signal_count / total) if total else 0.0,
                "products": products,
                "relevant_creatives": coverage["relevant_creatives"],
                "primary_hook_count": coverage["primary_hook_count"],
                "mentioned_count": coverage["mentioned_count"],
                "primary_hook_ratio": coverage["primary_hook_ratio"],
            }
        )

    return pd.DataFrame(rows)
