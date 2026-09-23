"""Deterministic calculations over Brio-style demo data.

Everything here is arithmetic: sums, rates, groupings, comparisons. Nothing
here decides what a number *means*: that interpretation is an AI agent's
job in a later milestone. Keeping that line sharp is why this file has no
notion of "good," "bad," "winning," or "worth testing."

Rates are always recomputed from summed numerators/denominators, never
averaged: averaging per-row CTR/CPA/ROAS values would overweight
low-volume days. Dividing by a zero denominator returns NaN, not 0 or an
error, so "no data" is never confused with "zero performance."
"""
from datetime import timedelta

import numpy as np
import pandas as pd

PERFORMANCE_SUM_COLUMNS = [
    "spend",
    "impressions",
    "clicks",
    "landing_page_views",
    "add_to_carts",
    "purchases",
    "revenue",
]

RATE_COLUMNS = ["ctr", "cpc", "cpa", "roas"]

# Noise/volume floors for trusting a performance comparison at all: below
# these, a single creative could swing the whole group's ROAS, or the
# comparison rests on a handful of conversions. Named here (not in the
# agent layer) since they're deterministic facts about how much volume a
# comparison needs to mean anything, not an interpretation; agents/
# intelligence/engine.py re-exports these for its own existing callers, and
# core/visual_performance.py uses them directly for the same reason.
PERFORMANCE_MIN_SPEND = 1500.0
PERFORMANCE_MIN_PURCHASES = 15
PERFORMANCE_MIN_RELATIVE_GAP = 0.10  # a difference under 10% is noise, not a real pattern


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator = numerator.astype(float)
    denominator = denominator.astype(float)
    return pd.Series(
        np.where(denominator == 0, np.nan, numerator / denominator),
        index=numerator.index,
    )


def add_performance_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add ctr/cpc/cpa/roas columns computed from existing sum columns.

    ctr = clicks / impressions
    cpc = spend / clicks
    cpa = spend / purchases
    roas = revenue / spend
    """
    df = df.copy()
    df["ctr"] = _safe_divide(df["clicks"], df["impressions"])
    df["cpc"] = _safe_divide(df["spend"], df["clicks"])
    df["cpa"] = _safe_divide(df["spend"], df["purchases"])
    df["roas"] = _safe_divide(df["revenue"], df["spend"])
    return df


def aggregate_performance(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Sum performance by any grouping columns present in df, then compute rates.

    E.g. by=["campaign_id"], by=["funnel_stage"], by=["creative_angle"],
    by=["message_style"], by=["format"], by=["creative_id"], or several at once.
    """
    grouped = df.groupby(by, as_index=False)[PERFORMANCE_SUM_COLUMNS].sum()
    return add_performance_metrics(grouped)


def attribute_style_leaders(
    df: pd.DataFrame,
    attribute_col: str,
    products: list[str] | None = None,
    min_spend: float = PERFORMANCE_MIN_SPEND,
    min_purchases: float = PERFORMANCE_MIN_PURCHASES,
    min_relative_gap: float = PERFORMANCE_MIN_RELATIVE_GAP,
) -> list[dict]:
    """Every (product, funnel_stage) cell where one value of `attribute_col`
    clearly leads (higher ROAS AND higher CTR than every other qualifying
    value in that same cell), ranked by the size of the ROAS gap, largest
    first. Generalizes the comparison agents/intelligence/engine.py's
    message_style_leaders uses for message_style, so the identical rule
    (never compare across funnel stages or products; require real volume;
    require a real gap, not noise) can be reused for any other creative
    attribute, e.g. a visual one, without duplicating the logic.

    Returns a list of dicts, empty if nothing qualifies (never forces a
    finding): product_name, funnel_stage, leader_value, leader_roas,
    leader_ctr, leader_spend, leader_purchases, runner_up_value,
    rest_best_roas, relative_gap, cell_table (the full qualifying
    breakdown for that cell, sorted best-ROAS-first).
    """
    scoped = df if products is None else df[df["product_name"].isin(products)]
    if scoped.empty:
        return []

    grouped = scoped.groupby(["product_name", "funnel_stage", attribute_col], as_index=False).agg(
        spend=("spend", "sum"),
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        purchases=("purchases", "sum"),
        revenue=("revenue", "sum"),
    )
    grouped["ctr"] = grouped["clicks"] / grouped["impressions"]
    grouped["cpa"] = grouped["spend"] / grouped["purchases"]
    grouped["roas"] = grouped["revenue"] / grouped["spend"]

    qualifying = grouped[(grouped["spend"] >= min_spend) & (grouped["purchases"] >= min_purchases)]

    leaders = []
    for (product, stage), group in qualifying.groupby(["product_name", "funnel_stage"]):
        if len(group) < 2:
            continue
        leader = group.loc[group["roas"].idxmax()]
        rest = group[group[attribute_col] != leader[attribute_col]]
        if rest.empty or (rest["ctr"] > leader["ctr"]).any():
            continue  # not a clean win on both metrics
        runner_up = rest.loc[rest["roas"].idxmax()]
        best_rest_roas = runner_up["roas"]
        if best_rest_roas <= 0:
            continue
        relative_gap = (leader["roas"] - best_rest_roas) / best_rest_roas
        if relative_gap < min_relative_gap:
            continue
        leaders.append(
            {
                "product_name": product,
                "funnel_stage": stage,
                "leader_value": leader[attribute_col],
                "leader_roas": leader["roas"],
                "leader_ctr": leader["ctr"],
                "leader_spend": leader["spend"],
                "leader_purchases": leader["purchases"],
                "runner_up_value": runner_up[attribute_col],
                "rest_best_roas": best_rest_roas,
                "relative_gap": relative_gap,
                "cell_table": group.sort_values("roas", ascending=False)[
                    [attribute_col, "spend", "purchases", "ctr", "cpa", "roas"]
                ].reset_index(drop=True),
            }
        )
    leaders.sort(key=lambda r: r["relative_gap"], reverse=True)
    return leaders


def aggregate_signals(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Count customer signals by any grouping columns present in df.

    E.g. by=["source"], by=["demo_theme_label"], by=["product_context"],
    by=["demo_intent_label"], by=["demo_sentiment_label"], or several at once.
    """
    counts = (
        df.groupby(by, as_index=False)
        .size()
        .rename(columns={"size": "signal_count"})
    )
    counts["share_of_total"] = counts["signal_count"] / len(df)
    return counts.sort_values("signal_count", ascending=False).reset_index(drop=True)


def summarize_signals(df: pd.DataFrame, theme_col: str = "demo_theme_label") -> dict:
    """The three Customer Signals summary numbers for an already-filtered set.

    signals_analyzed: row count. active_sources: distinct values of `source`
    actually present (not a fixed list, so a filter that removes a source
    also removes it from this count). themes_detected: distinct theme
    values present, same reasoning.
    """
    if df.empty:
        return {"signals_analyzed": 0, "active_sources": 0, "themes_detected": 0}
    return {
        "signals_analyzed": len(df),
        "active_sources": int(df["source"].nunique()),
        "themes_detected": int(df[theme_col].nunique()),
    }


def theme_movement(
    df: pd.DataFrame,
    start,
    end,
    theme_col: str = "demo_theme_label",
    date_col: str = "date",
) -> tuple[pd.DataFrame, bool]:
    """Per-theme signal counts for the selected [start, end] period, with
    change vs. the immediately preceding period of equal length.

    Same period-comparison philosophy as Overview's KPI deltas: the prior
    period is exactly as long as the selected one and ends the day before
    it starts (see previous_period), not a split of the selected range
    itself. A 30-day selection compares against the 30 days right before
    it, not its own first half against its own second half.

    Returns (table, movement_available). movement_available is False, and
    the table has no previous_count/change columns, when the dataset
    doesn't fully cover that prior period (see has_full_period) or the
    selected period has no signals, so a caller can omit the movement
    indicator instead of showing a number built on partial history.
    """
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)
    current = filter_date_range(df, start, end, date_col)
    total = len(current)

    counts = current[theme_col].value_counts().reset_index()
    counts.columns = [theme_col, "signal_count"]
    counts["share_of_total"] = counts["signal_count"] / total if total else 0.0
    counts = counts.sort_values("signal_count", ascending=False).reset_index(drop=True)

    prev_start, prev_end = previous_period(start, end)
    movement_available = total > 0 and has_full_period(df, prev_start, prev_end, date_col)
    if not movement_available:
        return counts, False

    previous_counts = filter_date_range(df, prev_start, prev_end, date_col)[theme_col].value_counts()
    counts["previous_count"] = counts[theme_col].map(previous_counts).fillna(0).astype(int)
    counts["change"] = counts["signal_count"] - counts["previous_count"]

    return counts, True


# A theme must gain at least this many signals versus the prior period to be
# called out as increasing: a noise floor so a 1-to-2 wobble is never
# presented as a trend (the same "never rest a claim on a handful of rows"
# philosophy as this module's other named floors). Intentionally smaller than
# the Intelligence Agent's EMERGING_MIN_CHANGE: this is a plain description
# of the chart, not a formal finding.
THEME_TAKEAWAY_MIN_CHANGE = 3


def theme_takeaway(
    theme_table: pd.DataFrame,
    movement_available: bool,
    min_change: int = THEME_TAKEAWAY_MIN_CHANGE,
    theme_col: str = "demo_theme_label",
) -> dict:
    """What to notice in a theme_movement table, derived only from that
    table (so it always reflects the selected period, product and source
    filters): the theme with the largest increase versus the prior period,
    if any increase clears `min_change`.

    Returns {"status": ...}: "increase" (plus theme, previous_count,
    signal_count, change), "no_increase" (movement is known and no theme
    rose by at least min_change), or "insufficient_history" (no full prior
    period exists, so no comparison is invented). Ties on change break
    deterministically: higher current count first, then theme name A to Z.
    Names no theme; works for any dataset.
    """
    if not movement_available or "change" not in theme_table.columns:
        return {"status": "insufficient_history"}
    risers = theme_table[theme_table["change"] >= min_change]
    if risers.empty:
        return {"status": "no_increase"}
    top = risers.sort_values(["change", "signal_count", theme_col], ascending=[False, False, True], kind="mergesort").iloc[0]
    return {
        "status": "increase",
        "theme": str(top[theme_col]),
        "previous_count": int(top["previous_count"]),
        "signal_count": int(top["signal_count"]),
        "change": int(top["change"]),
    }


THEME_PRODUCT_MIN_SIGNALS = 3  # a product needs at least this many mentions of a theme to count as "associated"


def theme_associated_products(
    df: pd.DataFrame,
    theme: str,
    theme_col: str = "demo_theme_label",
    product_col: str = "product_context",
    min_signals: int = THEME_PRODUCT_MIN_SIGNALS,
) -> pd.DataFrame:
    """Which products' customers most associate with a theme, and how much.

    Returns product, signal_count, share_of_theme_signals for every product
    with at least min_signals mentions of this theme (a floor so a single
    stray mention doesn't count as a real association), sorted by count
    descending. Used both to report "which products this theme touches" and
    to scope which products' creatives are "relevant" when measuring
    creative coverage of the theme (core/creative_coverage.py).
    """
    theme_rows = df[df[theme_col] == theme]
    if theme_rows.empty:
        return pd.DataFrame(columns=[product_col, "signal_count", "share_of_theme_signals"])
    counts = theme_rows[product_col].value_counts()
    total = len(theme_rows)
    qualifying = counts[counts >= min_signals]
    result = qualifying.reset_index()
    result.columns = [product_col, "signal_count"]
    result["share_of_theme_signals"] = result["signal_count"] / total
    return result


def filter_signals(
    df: pd.DataFrame,
    start=None,
    end=None,
    source=None,
    product=None,
    theme=None,
    intent=None,
    sentiment=None,
    search_text=None,
    date_col: str = "date",
    product_col: str = "product_context",
    theme_col: str = "demo_theme_label",
    intent_col: str = "demo_intent_label",
    sentiment_col: str = "demo_sentiment_label",
    text_col: str = "text",
) -> pd.DataFrame:
    """Apply any combination of Customer Signals filters, all AND-composed.

    Every filter is optional; omitting one (leaving it None) skips it
    entirely, so any combination, including all-None, composes correctly.
    search_text is a plain, deterministic, case-insensitive substring match
    against text_col (regex disabled), not a fuzzy or ranked search.
    """
    result = filter_date_range(df, start, end, date_col)
    if source is not None:
        result = result[result["source"] == source]
    if product is not None:
        result = result[result[product_col] == product]
    if theme is not None:
        result = result[result[theme_col] == theme]
    if intent is not None:
        result = result[result[intent_col] == intent]
    if sentiment is not None:
        result = result[result[sentiment_col] == sentiment]
    if search_text:
        result = result[result[text_col].str.contains(search_text, case=False, na=False, regex=False)]
    return result


def filter_date_range(df: pd.DataFrame, start=None, end=None, date_col: str = "date") -> pd.DataFrame:
    """Return rows with date_col within [start, end], either bound optional."""
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = pd.to_datetime(df[date_col])
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df[date_col] >= pd.to_datetime(start)
    if end is not None:
        mask &= df[date_col] <= pd.to_datetime(end)
    return df[mask]


def previous_period(start, end) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The immediately preceding, non-overlapping period of the same length.

    E.g. previous_period("2026-08-15", "2026-09-13") (30 days inclusive)
    returns ("2026-07-16", "2026-08-14"), the 30 days right before it.
    """
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)
    length = (end - start) + pd.Timedelta(days=1)
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - length + pd.Timedelta(days=1)
    return prev_start, prev_end


def has_full_period(df: pd.DataFrame, start, end, date_col: str = "date") -> bool:
    """Whether df has data covering the entire [start, end] window.

    Used to decide whether a "vs. previous period" comparison is trustworthy
    (the prior window is fully within the dataset) or should be omitted
    (the prior window would be partial or nonexistent).
    """
    if df.empty:
        return False
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
    return pd.to_datetime(start) >= df[date_col].min() and pd.to_datetime(end) <= df[date_col].max()


# Shared relative-period options (Milestone 19, Part 2A, introduced for
# Customer Signals; Milestone 28.8 promotes them here so Overview reuses the
# exact same options/default/resolution instead of a second, independently
# maintained implementation). Each label maps to a fixed lookback window
# ending at the dataset's own most recent date, never a raw custom
# date-range picker, so "Last 30 days" always means the same thing
# regardless of when the demo happens to run. previous_period/
# has_full_period above still decide whether a full preceding window of the
# same length actually exists before any page claims a comparison.
PERIOD_OPTIONS = {"Last 7 days": 7, "Last 30 days": 30, "Last 60 days": 60}
DEFAULT_PERIOD_LABEL = "Last 30 days"


def resolve_period(data_min, data_max, period_days: int) -> tuple:
    """The [start, end] window for a PERIOD_OPTIONS selection: always ends
    at data_max, and starts period_days earlier, clamped so it never
    precedes data_min. A "Last 60 days" selection against a dataset with
    less than 60 days of history simply starts at data_min; it never
    fabricates dates outside the actual dataset.
    """
    return max(data_min, data_max - timedelta(days=period_days - 1)), data_max


def _summed(df: pd.DataFrame, by: list[str] | None) -> pd.DataFrame:
    if by:
        return df.groupby(by, as_index=False)[PERFORMANCE_SUM_COLUMNS].sum()
    return df[PERFORMANCE_SUM_COLUMNS].sum().to_frame().T.reset_index(drop=True)


def compare_periods(
    df: pd.DataFrame,
    period_a: tuple,
    period_b: tuple,
    by: list[str] | None = None,
    date_col: str = "date",
) -> pd.DataFrame:
    """Compare summed performance (and derived rates) between two date ranges.

    period_a / period_b are (start, end) date tuples/strings. When `by` is
    given, comparison rows are per group instead of one overall row. A group
    with no rows in one period gets 0s for that period's sums (real absence
    of activity), while rate columns stay NaN for a zero denominator.
    Returns one row (or one row per group) with _period_a / _period_b sums
    and rates, plus _delta and _pct_change for every metric.
    """
    df_a = filter_date_range(df, period_a[0], period_a[1], date_col)
    df_b = filter_date_range(df, period_b[0], period_b[1], date_col)

    sums_a = _summed(df_a, by)
    sums_b = _summed(df_b, by)

    if by:
        merged = sums_a.merge(sums_b, on=by, how="outer", suffixes=("_period_a", "_period_b"))
        for col in PERFORMANCE_SUM_COLUMNS:
            merged[f"{col}_period_a"] = merged[f"{col}_period_a"].fillna(0)
            merged[f"{col}_period_b"] = merged[f"{col}_period_b"].fillna(0)
    else:
        merged = pd.concat(
            [sums_a.add_suffix("_period_a"), sums_b.add_suffix("_period_b")], axis=1
        )

    for suffix in ("_period_a", "_period_b"):
        renamed = merged[[f"{c}{suffix}" for c in PERFORMANCE_SUM_COLUMNS]].rename(
            columns={f"{c}{suffix}": c for c in PERFORMANCE_SUM_COLUMNS}
        )
        rates = add_performance_metrics(renamed)
        for rate_col in RATE_COLUMNS:
            merged[f"{rate_col}{suffix}"] = rates[rate_col]

    for metric in PERFORMANCE_SUM_COLUMNS + RATE_COLUMNS:
        col_a, col_b = f"{metric}_period_a", f"{metric}_period_b"
        merged[f"{metric}_delta"] = merged[col_b] - merged[col_a]
        merged[f"{metric}_pct_change"] = _safe_divide(merged[f"{metric}_delta"], merged[col_a])

    return merged
