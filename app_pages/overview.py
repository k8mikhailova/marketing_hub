"""Overview page: What needs your attention -> Account performance.

All KPI math, aggregation, and insight logic live in core/ (data.py,
analytics.py, insights.py, assets.py). This file only wires those
functions to Streamlit widgets and lays out the result. No calculation
happens here.

Milestone 18 redesign: the page used to lead with a raw KPI dashboard,
then a "Marketing Intelligence" row of the same 3 insights, then a
hardcoded "Action Center" whose own items were explicitly NOT derived
from real data (a placeholder for a future review queue). That put the
least useful section (a static placeholder) last and the most useful one
(interpretation) second, behind bare numbers. This version leads with
"What needs your attention": up to 3 real, data-driven items built from
the SAME core.insights functions the old "Marketing Intelligence" row
already called (no new findings logic, no duplicated Intelligence Agent
logic) plus, when one exists in this session, the current experiment
result. Account-level KPIs/trend move below that, as context once the
headline is already understood.
"""
from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from agents.performance.engine import EVIDENCE_STRENGTH_LABELS
from core import ui
from core.analytics import aggregate_performance, compare_periods, filter_date_range, has_full_period, previous_period
from core.assets import resolve_image_for_product
from core.data import load_customer_signals, load_performance_with_creatives
from core.insights import emerging_signal, next_opportunity, winning_pattern
from core.shell import current_client

TREND_METRICS = {"ROAS": "roas", "Revenue": "revenue", "CPA": "cpa", "CTR": "ctr"}


def _fmt_currency(value: float, decimals: int = 0) -> str:
    return "-" if pd.isna(value) else f"${value:,.{decimals}f}"


def _fmt_ratio(value: float, suffix: str = "x") -> str:
    return "-" if pd.isna(value) else f"{value:.2f}{suffix}"


def _fmt_percent(value: float) -> str:
    return "-" if pd.isna(value) else f"{value:.2%}"


def _fmt_count(value: float) -> str:
    return "-" if pd.isna(value) else f"{value:,.0f}"


def _render_kpi(col, label, value_str, row, metric, higher_is_good, comparison_valid, period_days):
    delta_str = None
    delta_color = "off"
    if comparison_valid:
        pct = row.get(f"{metric}_pct_change")
        if pct is not None and not pd.isna(pct):
            delta_str = f"{pct:+.1%} vs prior {period_days}d"
            delta_color = "normal" if higher_is_good else "inverse"
    col.metric(label, value_str, delta=delta_str, delta_color=delta_color)


def _md_safe(text: str) -> str:
    """Escape '$' so markdown/caption rendering never mistakes two currency
    values in one string for a LaTeX math span (a real rendering bug this
    page had: "...($89.70 CPA) versus...($112.51 CPA)" rendered broken)."""
    return text.replace("$", "\\$")


def _signal_facts(data: dict) -> tuple[str, str]:
    """(facts line, why-it-matters line) for an emerging_signal Insight,
    reusing its own data dict and the exact wording this page already
    established for each kind, never inventing new numbers."""
    if data.get("kind") == "growth":
        return (
            f'{data["second_half"]} mentions · +{data["delta"]} vs prior period',
            "Largest increase of any customer-conversation theme.",
        )
    return (
        f'{data["count"]} of {data["total"]} signals',
        "Most-mentioned theme this period (no clear growth).",
    )


def _pattern_facts(data: dict) -> tuple[str, str]:
    """(facts line, why-it-matters line) for a winning_pattern Insight."""
    if data.get("kind") == "tradeoff":
        eff, att = data["efficiency"], data["attention"]
        return (f'{eff["roas"]:.2f}x ROAS · {att["ctr"]:.2%} CTR', data["interpretation"])
    return (
        f'{data["roas"]:.2f}x ROAS · {data["lift"]:.1f}x peer avg',
        f'Outperforming its peers within {data["context"]}.',
    )


def _opportunity_facts(data: dict) -> tuple[str, str]:
    """(facts line, why-it-matters line) for a next_opportunity Insight."""
    return (
        f'{data["signal_share"]:.0%} of signals · {data["primary_hook_count"]}/{data["relevant_creatives"]} creatives lead with it',
        data["recommendation"],
    )


def _render_feed_item(eyebrow: str, insight, facts_fn, cta_label: str, cta_page: str, image=None) -> None:
    """One row in the "What needs your attention" feed (Part 1, badge
    treatment per Milestone 20 Part 2): a consistent category BADGE (never
    a mismatched decorative symbol), ONE conclusion (the insight's own
    headline), 1-2 compact supporting facts, and ONE obvious next action,
    in a consistent vertical rhythm rather than an equal-height bordered
    card. Evidence stays one quiet expander away, never competing with
    the action for attention.
    """
    facts, why = facts_fn(insight.data)
    ui.badge_row([eyebrow.upper()])
    st.markdown(f"**{insight.headline}**")
    st.caption(_md_safe(facts))
    st.write(why)
    if image is not None:
        creative_id, image_path = image
        img_col, _ = st.columns([1, 4])
        with img_col:
            st.image(str(image_path), width=80)
        ui.muted(f"Publicly visible Brio creative ({creative_id}): evidence only, not simulated performance.")

    action_col, evidence_col = st.columns([1, 1])
    with action_col:
        st.page_link(cta_page, label=f"{cta_label} →")
    with evidence_col:
        with st.expander("View evidence"):
            st.write(_md_safe(insight.explanation))
            for line in insight.evidence_lines:
                st.markdown(f"- {_md_safe(line)}")
            if insight.evidence_table is not None:
                st.dataframe(insight.evidence_table, hide_index=True, use_container_width=True)


def _render_experiment_feed_item(client_id: str) -> bool:
    """The one attention item this page reads from session state rather
    than core.insights: a demo test the marketer already ran on
    Experiments, in THIS session, for the CURRENT client. Never a new
    finding, never persisted, never fabricated when nothing has run yet
    (returns False and renders nothing)."""
    handoff = st.session_state.get("experiment_handoff")
    analysis = st.session_state.get("experiment_analysis")
    if not handoff or handoff.get("client_id") != client_id or analysis is None:
        return False

    ui.badge_row(["Experiment result"])
    st.markdown(f"**{analysis.headline}**")
    st.caption(f"{EVIDENCE_STRENGTH_LABELS.get(analysis.evidence_strength, analysis.evidence_strength)} evidence so far.")
    st.write(analysis.recommendation_note)
    st.page_link("app_pages/experiments.py", label="Review experiment →")
    return True


def _render_attention_section(client_id: str) -> None:
    ui.section_header("What needs your attention")

    opportunity = next_opportunity(client_id)
    opportunity_image = None
    if opportunity.found and "product" in opportunity.data:
        opportunity_image = resolve_image_for_product(client_id, opportunity.data["product"])

    signal = emerging_signal(client_id)
    signal_eyebrow = "Emerging signal" if signal.found and signal.data.get("kind") == "growth" else "Customer signal"

    # (eyebrow, insight, facts_fn, cta_label, cta_page, image)
    candidates = [
        (signal_eyebrow, signal, _signal_facts, "Explore opportunity", "app_pages/intelligence.py", None),
        ("Creative opportunity", opportunity, _opportunity_facts, "Develop creative", "app_pages/creative_lab.py", opportunity_image),
        ("Performance pattern", winning_pattern(client_id), _pattern_facts, "View performance", "app_pages/intelligence.py", None),
    ]
    found_candidates = [c for c in candidates if c[1].found]

    shown = 0
    if _render_experiment_feed_item(client_id):
        shown += 1
        st.divider()

    for i, (eyebrow, insight, facts_fn, cta_label, cta_page, image) in enumerate(found_candidates):
        if shown >= 3:
            break
        _render_feed_item(eyebrow, insight, facts_fn, cta_label, cta_page, image)
        shown += 1
        if i < len(found_candidates) - 1 and shown < 3:
            st.divider()

    if shown == 0:
        ui.empty_state("Nothing needs attention yet.", "Once customer signals and performance data accumulate, this section fills in automatically.")


client = current_client()
client_id = client["client_id"]

joined = load_performance_with_creatives(client_id)
signals = load_customer_signals(client_id)

ui.inject_base_styles()
ui.page_header(f"{client['name']} | Marketing Overview", badges=["Demo data"])

# --- Account performance: comes first, establishes context -------------------
ui.section_header("Account performance", "How is marketing performing right now?")

data_min = joined["date"].min().date()
data_max = joined["date"].max().date()
default_start = max(data_min, data_max - timedelta(days=29))

selected_range = st.date_input(
    "Date range",
    value=(default_start, data_max),
    min_value=data_min,
    max_value=data_max,
)
if isinstance(selected_range, (list, tuple)) and len(selected_range) == 2:
    start, end = selected_range
else:
    start, end = default_start, data_max

period_days = (end - start).days + 1
prev_start, prev_end = previous_period(start, end)
comparison_valid = has_full_period(joined, prev_start, prev_end)

cmp = compare_periods(joined, period_a=(prev_start, prev_end), period_b=(start, end)).iloc[0]

row1 = st.columns(4)
_render_kpi(row1[0], "Ad spend", _fmt_currency(cmp["spend_period_b"]), cmp, "spend", True, comparison_valid, period_days)
_render_kpi(row1[1], "Revenue", _fmt_currency(cmp["revenue_period_b"]), cmp, "revenue", True, comparison_valid, period_days)
_render_kpi(row1[2], "ROAS", _fmt_ratio(cmp["roas_period_b"]), cmp, "roas", True, comparison_valid, period_days)
_render_kpi(row1[3], "Purchases", _fmt_count(cmp["purchases_period_b"]), cmp, "purchases", True, comparison_valid, period_days)

row2 = st.columns(4)
_render_kpi(row2[0], "CTR", _fmt_percent(cmp["ctr_period_b"]), cmp, "ctr", True, comparison_valid, period_days)
_render_kpi(row2[1], "CPC", _fmt_currency(cmp["cpc_period_b"], decimals=2), cmp, "cpc", False, comparison_valid, period_days)
_render_kpi(row2[2], "CPA", _fmt_currency(cmp["cpa_period_b"]), cmp, "cpa", False, comparison_valid, period_days)

if not comparison_valid:
    st.caption("Not enough prior history for a full comparison period, showing totals only.")

metric_label = st.radio("Trend metric", list(TREND_METRICS.keys()), horizontal=True)
metric_col = TREND_METRICS[metric_label]

daily = aggregate_performance(filter_date_range(joined, start, end), by=["date"]).sort_values("date")
chart = (
    alt.Chart(daily)
    .mark_line(point=True, strokeWidth=2, color=ui.ACCENT_COLOR)
    .encode(
        x=alt.X("date:T", title=None),
        y=alt.Y(f"{metric_col}:Q", title=metric_label),
        tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip(f"{metric_col}:Q", title=metric_label, format=".2f")],
    )
    .properties(height=220)
)
st.altair_chart(chart, use_container_width=True)

st.divider()

# --- What needs your attention: comes after, now that context is set --------
_render_attention_section(client_id)
