"""Customer Signals page: the evidence layer for customer and market intelligence.

Answers what sources are being listened to, what themes appear in those
signals, and what customers are actually saying. This page does not
interpret signals into marketing recommendations: that belongs to Insights
(the page previously called "Marketing Intelligence"; see app_pages/
intelligence.py) and, later, Creative Lab. All calculation lives in
core/analytics.py; this file only wires filters to widgets and renders.
"""
import altair as alt
import streamlit as st

from core import ui
from core.analytics import (
    DEFAULT_PERIOD_LABEL,
    PERIOD_OPTIONS,
    aggregate_signals,
    filter_signals,
    resolve_period,
    summarize_signals,
    theme_movement,
    theme_takeaway,
)
from core.data import load_customer_signals
from core.shell import current_client

FEED_PAGE_SIZE = 10
ALL_OPTION = "All"

# PERIOD_OPTIONS/DEFAULT_PERIOD_LABEL originated here (Milestone 19, Part
# 2A) and now live in core/analytics.py (Milestone 28.8), shared with
# Overview, so both pages express "recent history" identically instead of
# two independent implementations. previous_period/has_full_period
# (core/analytics.py, unchanged) still decide whether a full preceding
# window of the same length actually exists before this page claims a
# comparison.

# A theme chart's per-row and floor height (Part 2B): tall enough that
# Vega-Lite never needs to drop a label to fit, and never so short (a
# single-theme filter) that the chart reads as a broken thin strip.
THEME_ROW_HEIGHT = 34
MIN_CHART_HEIGHT = 90

# Traceability hook: another page can pre-select a theme here by setting this
# session_state key before switching to this page (e.g. a future click on
# Overview's "Taste & odor: 17 -> 40" card). Not wired from any other page
# yet, but reading it here costs nothing and keeps that door open.
THEME_PREFILL_KEY = "signals_prefill_theme"
THEME_FILTER_KEY = "signals_theme_filter"


def _humanize_label(value: str) -> str:
    """Display formatting only; never touches the stored value.

    Converts a raw, single-token demo preprocessing label into a normal
    phrase: "problem_awareness" -> "Problem awareness", "neutral" ->
    "Neutral". A value that already contains a space (theme names, product
    names, source names) is returned unchanged: those are already curated
    multi-word labels, and blindly re-casing one (e.g. "Q60 Countertop
    Dispenser") would lowercase words that are supposed to stay capitalized.
    """
    if " " in value:
        return value
    return value.replace("_", " ").capitalize()


def _reset_if_stale(key: str, valid_options: list) -> None:
    """Reset a remembered filter choice back to "All" if changing the global
    filters made it fall out of range, so the selectbox never crashes on a
    stale session_state value that isn't in its current options list."""
    if key in st.session_state and st.session_state[key] not in valid_options:
        st.session_state[key] = ALL_OPTION


def _feed_limit_key(signature: tuple) -> str:
    return "signals_feed_limit::" + "|".join(str(part) for part in signature)


def _movement_label(count: int, change: int | None) -> str:
    """"40 ↑ 23" / "40 ↓ 5" / "40 →" / "40" (Part 2C): a compact per-theme
    movement label, direction-first rather than a repeated "vs prior Nd"
    caveat on every bar (that comparison window is stated once, outside
    the chart, only when it is NOT available)."""
    if change is None:
        return str(count)
    if change > 0:
        return f"{count} ↑ {change}"
    if change < 0:
        return f"{count} ↓ {abs(change)}"
    return f"{count} →"


def _takeaway_text(takeaway: dict) -> str:
    """The one-sentence "what to notice" for the theme chart, from
    core.analytics.theme_takeaway. Honest about missing history: it never
    describes a trend the data cannot support.
    """
    if takeaway["status"] == "increase":
        return (
            f"{ui.theme_label(takeaway['theme'])} showed the largest increase, rising from "
            f"{takeaway['previous_count']} to {takeaway['signal_count']} mentions."
        )
    if takeaway["status"] == "no_increase":
        return "No customer theme increased meaningfully during this period."
    return "There isn't enough prior-period data to identify a movement trend yet."


def _render_signal_entry(row) -> None:
    """A subtle feed row (Milestone 20, Part 3), not a bordered card: the
    customer's own language is the most visually prominent part of the
    row (plain body text, not a caption); source/theme are quiet, scannable
    badges instead of one of four equal-weight metadata columns, so
    someone scanning the page can immediately see where a signal came
    from without the row competing with the theme analysis above it.
    Metadata (product/intent/sentiment) is smaller and muted, and a thin
    rule (never a full st.divider(), too heavy for supporting evidence)
    separates one row from the next.
    """
    badge_col, date_col = st.columns([4, 1])
    with badge_col:
        ui.badge_row([row["source"], row["demo_theme_label"]])
    with date_col:
        ui.muted(row["date"].strftime("%Y-%m-%d"))
    ui.safe_paragraph(row["text"])
    ui.muted(
        f"{row['product_context']} · {_humanize_label(row['demo_intent_label'])} · "
        f"{_humanize_label(row['demo_sentiment_label'])}"
    )
    st.markdown('<div class="ui-feed-divider"></div>', unsafe_allow_html=True)


client = current_client()
client_id = client["client_id"]

signals = load_customer_signals(client_id)

ui.inject_base_styles()
ui.page_header("Customer Signals", "Customer conversations and market signals across connected sources.", badges=["Demo data"])

# --- Filters: one analysis, three controls (Part 2D) -------------------------
data_min = signals["date"].min().date()
data_max = signals["date"].max().date()

filter_cols = st.columns(3)
with filter_cols[0]:
    period_label = st.selectbox(
        "Period", list(PERIOD_OPTIONS.keys()),
        index=list(PERIOD_OPTIONS.keys()).index(DEFAULT_PERIOD_LABEL),
        key="signals_period",
    )
period_days_selected = PERIOD_OPTIONS[period_label]
start, end = resolve_period(data_min, data_max, period_days_selected)

product_options = [ALL_OPTION] + sorted(signals["product_context"].unique())
with filter_cols[1]:
    selected_product = st.selectbox("Product", product_options, key="signals_product_filter")

source_options = [ALL_OPTION] + sorted(signals["source"].unique())
with filter_cols[2]:
    selected_source = st.selectbox("Source", source_options, key="signals_source_filter")

product_filter = None if selected_product == ALL_OPTION else selected_product
source_filter = None if selected_source == ALL_OPTION else selected_source

# Product/source filtered, but NOT date filtered: theme_movement needs
# visibility into the period before `start` too, to compare against it.
filtered_scope = filter_signals(signals, product=product_filter, source=source_filter)

filtered_global = filter_signals(filtered_scope, start=start, end=end)

st.divider()

# --- Conversation Themes: the main story ------------------------------------
ui.section_header("What are customers talking about?", "Theme movement across the selected period.")

summary = summarize_signals(filtered_global)
ui.metric_row([
    ("Signals analyzed", f"{summary['signals_analyzed']:,}"),
    ("Active sources", str(summary["active_sources"])),
    ("Themes detected", str(summary["themes_detected"])),
])

if filtered_global.empty:
    ui.empty_state("No signals match the current filters.")
else:
    period_days = (end - start).days + 1
    # filtered_scope (product/source filtered, not date filtered) so the
    # function can see the prior period too, not just the selected one.
    theme_table, movement_available = theme_movement(filtered_scope, start, end)
    n_themes = len(theme_table)

    ui.callout("What to notice", _takeaway_text(theme_takeaway(theme_table, movement_available)))

    if movement_available:
        theme_table["movement_label"] = theme_table.apply(
            lambda r: _movement_label(int(r["signal_count"]), int(r["change"])), axis=1
        )
    else:
        theme_table["movement_label"] = theme_table["signal_count"].apply(_movement_label, change=None)

    # Part 2B: a small/filtered dataset must never lose a theme label or
    # collapse into an awkward strip. labelOverlap=False stops Vega-Lite
    # from silently dropping a category label it thinks would overlap
    # (the actual cause of themes disappearing from the y-axis under a
    # tight filter); a per-theme row-height floor, plus an overall minimum
    # chart height, keeps 1-2 themes looking like an intentional chart
    # rather than a collapsed sliver. Sorted by current-period count
    # descending throughout (sort="-x", matching theme_movement's own
    # sort), consistent regardless of how many themes remain.
    base = alt.Chart(theme_table).encode(
        y=alt.Y("demo_theme_label:N", sort="-x", title=None, axis=alt.Axis(labelLimit=0, labelOverlap=False)),
        x=alt.X("signal_count:Q", title="Signals in selected period", axis=alt.Axis(format="d", tickMinStep=1)),
    )
    tooltip_fields = [
        alt.Tooltip("demo_theme_label:N", title="Theme"),
        alt.Tooltip("signal_count:Q", title="Signals in selected period"),
        alt.Tooltip("share_of_total:Q", title="Share of period", format=".0%"),
    ]
    if movement_available:
        tooltip_fields.append(alt.Tooltip("change:Q", title=f"Change vs prior {period_days}d", format="+d"))
    bars = base.mark_bar(color=ui.ACCENT_COLOR).encode(tooltip=tooltip_fields)
    labels = base.mark_text(align="left", dx=4).encode(text="movement_label:N")
    chart_height = max(MIN_CHART_HEIGHT, THEME_ROW_HEIGHT * n_themes + 40)
    theme_chart = (bars + labels).properties(height=chart_height)
    st.altair_chart(theme_chart, use_container_width=True)
    if not movement_available:
        st.caption(
            f"Not enough history before {start} for a full prior {period_days}-day period; showing counts only."
        )

# Milestone 20, Part 3: Source Coverage belongs to the theme analysis above
# it (a supporting breakdown of the SAME filtered signals), not its own
# isolated band between two dividers - no divider directly above it, so
# it reads as "more about this" rather than a new section.
with st.expander("Source coverage"):
    if filtered_global.empty:
        st.caption("No signals match the current filters.")
    else:
        by_source = aggregate_signals(filtered_global, by=["source"])
        source_chart = (
            alt.Chart(by_source)
            .mark_bar(color=ui.ACCENT_COLOR)
            .encode(
                y=alt.Y("source:N", sort="-x", title=None, axis=alt.Axis(labelLimit=0, labelOverlap=False)),
                x=alt.X("signal_count:Q", title="Signals", axis=alt.Axis(format="d", tickMinStep=1)),
                tooltip=[
                    alt.Tooltip("source:N", title="Source"),
                    alt.Tooltip("signal_count:Q", title="Signals"),
                    alt.Tooltip("share_of_total:Q", title="Share", format=".0%"),
                ],
            )
            .properties(height=max(MIN_CHART_HEIGHT, THEME_ROW_HEIGHT * len(by_source) + 20))
        )
        st.altair_chart(source_chart, use_container_width=True)

st.divider()

# --- Signal Feed: supporting evidence ----------------------------------------
ui.section_header("Signal feed", "Individual customer signals behind the theme analysis above.")
ui.badge_row(["Simulated customer signals"])

theme_options = [ALL_OPTION] + sorted(filtered_global["demo_theme_label"].unique())
intent_options = [ALL_OPTION] + sorted(filtered_global["demo_intent_label"].unique())
sentiment_options = [ALL_OPTION] + sorted(filtered_global["demo_sentiment_label"].unique())

# Global filters (date/product/source) can change which themes/intents/
# sentiments even exist in scope. Reset any remembered feed-filter choice
# that's no longer valid before the widgets below read it, so changing a
# global filter never crashes a feed filter on a stale value.
_reset_if_stale(THEME_FILTER_KEY, theme_options)
_reset_if_stale("signals_intent_filter", intent_options)
_reset_if_stale("signals_sentiment_filter", sentiment_options)

# Traceability hook: honor a pre-selected theme only if it's a valid option
# under the current global filters, so a stale or out-of-scope hint can
# never make the selectbox raise.
prefill_theme = st.session_state.pop(THEME_PREFILL_KEY, None)
if prefill_theme in theme_options and THEME_FILTER_KEY not in st.session_state:
    st.session_state[THEME_FILTER_KEY] = prefill_theme

feed_filter_cols = st.columns(4)
with feed_filter_cols[0]:
    search_query = st.text_input("Search signal text", key="signals_search_text")

with feed_filter_cols[1]:
    selected_theme = st.selectbox("Theme", theme_options, key=THEME_FILTER_KEY)

with feed_filter_cols[2]:
    selected_intent = st.selectbox(
        "Intent", intent_options, format_func=_humanize_label, key="signals_intent_filter"
    )

with feed_filter_cols[3]:
    selected_sentiment = st.selectbox(
        "Sentiment", sentiment_options, format_func=_humanize_label, key="signals_sentiment_filter"
    )

feed = filter_signals(
    filtered_global,
    theme=None if selected_theme == ALL_OPTION else selected_theme,
    intent=None if selected_intent == ALL_OPTION else selected_intent,
    sentiment=None if selected_sentiment == ALL_OPTION else selected_sentiment,
    search_text=search_query,
)
feed = feed.sort_values(["date", "signal_id"], ascending=[False, False])

st.caption(f"{len(feed)} matching signal{'s' if len(feed) != 1 else ''}")

limit_key = _feed_limit_key((selected_theme, selected_intent, selected_sentiment, search_query, selected_product, selected_source, str(start), str(end)))
if limit_key not in st.session_state:
    st.session_state[limit_key] = FEED_PAGE_SIZE

if feed.empty:
    st.caption("No signals match the current filters.")
else:
    visible = feed.head(st.session_state[limit_key])
    for _, row in visible.iterrows():
        _render_signal_entry(row)

    if len(feed) > st.session_state[limit_key]:
        if st.button(f"Show more ({len(feed) - st.session_state[limit_key]} remaining)"):
            st.session_state[limit_key] += FEED_PAGE_SIZE
            st.rerun()
