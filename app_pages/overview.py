"""Overview page: What needs your attention -> Account performance.

All KPI math and aggregation live in core/ (data.py, analytics.py), and
all findings come from the Intelligence Agent (agents/intelligence/
engine.py). This file only wires those to Streamlit widgets and lays out
the result. No calculation happens here.

Milestone 18 redesign: the page used to lead with a raw KPI dashboard,
then a "Marketing Intelligence" row of the same 3 insights, then a
hardcoded "Action Center" whose own items were explicitly NOT derived
from real data (a placeholder for a future review queue). That put the
least useful section (a static placeholder) last and the most useful one
(interpretation) second, behind bare numbers. This version leads with
"What needs your attention" (see below for what it summarizes today).
Account-level KPIs/trend move below that, as context once the headline is
already understood.

Milestones 25-26: "What needs your attention" is an executive SUMMARY, not
a list of per-finding tasks, and it summarizes the SAME findings the rest
of the product uses. The Intelligence Agent
(agents.intelligence.engine.generate_findings) is the single source of
truth for marketer-facing findings: Overview previews them, Insights shows
them with evidence, and the Creative Strategist consumes them to build the
Creative Plan. This page previously derived its own, different insights
from core.insights (a pre-Intelligence-Agent preview layer), which is why
its "performance" item could describe a different product and funnel stage
than the Insights page; it no longer imports core.insights at all. The old
per-item actions belonged to the pre-Creative-Plan model and are gone; one
quiet "View Insights" link remains. Experiment learnings finished this
session (Performance Agent output) appear in their own labeled group after
the current findings and never displace them.
"""
from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from agents.intelligence.engine import generate_findings
from agents.performance.engine import EVIDENCE_STRENGTH_LABELS
from core import ui
from core.analytics import aggregate_performance, compare_periods, filter_date_range, has_full_period, previous_period
from core.data import load_customer_signals, load_performance_with_creatives
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


# Overview-only presentation order for the current findings (an executive
# story: what customers are doing, where our creative falls short, what
# performance context exists). Keyed by the Finding's own TYPE, never an id
# or title, so it works for any data; a type not listed here keeps the
# Intelligence Agent's own order after the listed ones, and an absent type
# is simply not rendered. The Agent's priority order (what Insights and the
# Creative Plan see) is untouched: this only reorders a copy for display.
OVERVIEW_TYPE_ORDER = ["Emerging Opportunity", "Messaging Gap", "Performance Pattern"]


def _overview_order(findings: list) -> list:
    rank = {t: i for i, t in enumerate(OVERVIEW_TYPE_ORDER)}
    return sorted(findings, key=lambda f: rank.get(f.type, len(OVERVIEW_TYPE_ORDER)))


def _render_finding_summary(finding) -> None:
    """One current Intelligence Agent finding as a compact, quiet summary
    card: its category badge (the finding's own type, the same badge
    Insights shows), its title (strongest), and its one-sentence summary
    (secondary; real numbers straight from the Finding). No evidence, no
    confidence line, no action: Insights answers "why does the system think
    that"; this answers "what does it want me to know".
    """
    with ui.card("standard", rhythm=True, soft=True):
        ui.badge_row([finding.type.upper()])
        ui.text_stack(finding.title, finding.summary, bold_primary=True)


def _completed_experiment_analyses(client_id: str) -> list[tuple[dict, object]]:
    """(handoff, ConceptExperimentAnalysis) for every experiment the marketer
    already ran in THIS session for the CURRENT client (Experiments V2 keeps
    these in per-proposal_id dicts). Never a new finding, never persisted,
    and empty when nothing has run yet.
    """
    handoffs = st.session_state.get("experiment_handoffs", {})
    analyses = st.session_state.get("experiment_analyses", {})
    completed = []
    for proposal_id, handoff in handoffs.items():
        if handoff.get("client_id") != client_id or handoff.get("status") != "results_pending":
            continue
        analysis = analyses.get(proposal_id)
        if analysis is not None:
            completed.append((handoff, analysis))
    return completed


def _render_experiment_learning(handoff: dict, analysis) -> None:
    """A finished demo experiment, summarized in the same card language as
    the findings but kept in its own group: the Performance Agent's own
    headline and learning statement, its evidence tier, and the truthful
    "proposed, pending review" status. Deliberately a different badge from
    the Intelligence Agent's findings: this is what an experiment showed,
    not what the market data suggests.
    """
    with ui.card("standard", rhythm=True, soft=True):
        ui.badge_row(["EXPERIMENT LEARNING"])
        ui.text_stack(f"{handoff['customer_theme']} messaging test: {analysis.headline}", analysis.learning_statement, bold_primary=True)
        evidence = EVIDENCE_STRENGTH_LABELS.get(analysis.evidence_strength, analysis.evidence_strength)
        st.caption(f"{evidence} evidence so far. Proposed learning, pending review.")


# Current findings are never crowded out by experiment learnings: every
# current Intelligence finding is always shown first, and at most this many
# experiment learnings follow it, in a separately labeled group.
MAX_EXPERIMENT_LEARNINGS = 2

def _attention_subtitle(has_experiments: bool) -> str:
    """State-aware: never implies experiment evidence before an experiment
    has actually been run in this session."""
    areas = ["customer conversation", "creative coverage", "performance"]
    if has_experiments:
        areas.append("experiments")
    return f"The most important things the system is seeing across {', '.join(areas[:-1])}, and {areas[-1]}."


def _render_attention_section(client_id: str) -> None:
    """A short executive preview of what the system currently wants the
    marketer to know: the SAME Finding objects the Insights page renders
    (agents.intelligence.engine.generate_findings, same max_findings=3, so
    Overview, Insights and, through the Strategist, Creative Lab can never
    disagree about "what the system learned"), shown in an Overview-specific
    order, plus any experiment learning finished this session. Each item is
    a summary, not a task: the only navigation is one quiet section-level
    link to the full Insights page.
    """
    experiments = _completed_experiment_analyses(client_id)[:MAX_EXPERIMENT_LEARNINGS]
    ui.section_header("What needs your attention", _attention_subtitle(bool(experiments)))

    findings = _overview_order(generate_findings(client_id, max_findings=3))

    if not findings and not experiments:
        ui.empty_state("Nothing needs attention yet.", "Once customer signals and performance data accumulate, this section fills in automatically.")
        return

    for finding in findings:
        _render_finding_summary(finding)

    if experiments:
        ui.section_header("Recent experiment learning", level="subsection")
        for handoff, analysis in experiments:
            _render_experiment_learning(handoff, analysis)

    st.page_link("app_pages/intelligence.py", label="View Insights →")


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
