"""Marketing Insights page (sidebar/page title: "Insights"; user-facing
page title: "Marketing Insights"; backend module/agent names are
unchanged, see Milestone 20's own product-language-only rename): customer
conversation, creative coverage, and performance connected into
evidence-based findings.

Customer Signals answers what customers are saying. This page answers what
that means once it's combined with what current creative emphasizes and
how that creative is actually performing. All finding generation lives in
agents/intelligence/engine.py (the Intelligence Agent's deterministic
preview implementation, deliberately NOT renamed: this is a product-
language change, not an architecture rename); all supporting calculation
lives in core/. This file only renders what those layers return.
"""
import altair as alt
import streamlit as st

from agents.intelligence.engine import (
    EXPERIMENT_WORTHY_TYPES,
    PERFORMANCE_MIN_PURCHASES,
    PERFORMANCE_MIN_SPEND,
    generate_findings,
    message_style_leaders,
)
from core import ui
from core.analytics import aggregate_performance
from core.creative_coverage import theme_coverage_landscape
from core.data import load_creative_catalog, load_customer_signals, load_performance_with_creatives
from core.shell import current_client


def _humanize(value: str) -> str:
    """Display formatting only: "benefit_plus_proof" -> "benefit plus proof"."""
    return value.replace("_", " ")


def _jump_to_performance_patterns(product: str) -> None:
    """Milestone 20, Part 6: a state-assisted "next action" for a finding
    that isn't experiment-worthy (Performance Pattern), since Streamlit's
    st.page_link can't reliably anchor-scroll to a section on the SAME
    page (confirmed: appending a URL fragment fails the same path
    validation that produces "Could not find page"). This is simpler and
    actually more useful than a scroll: it pre-filters the Creative
    performance patterns section below to the SAME product this finding
    is about (finding.products[0], already-existing data, never a new
    computation), the same session-state-prefill pattern Customer Signals
    already uses for its own theme filter.
    """
    st.session_state["intel_perf_product"] = product


def _render_brief_item(number: int, finding) -> None:
    """One entry in the Insights Brief (Milestone 19 Part 3, hierarchy
    strengthened in Milestone 20 Part 5): a visually-noticeable (not
    enormous) number beside a real type badge, the finding's own title as
    the dominant element, summary/why_it_matters visually quieter, then
    intentional space before the action row. Deliberately not a card:
    these are 3 ranked conclusions from one analyst brief, not 3 unrelated
    products to compare side by side, so there is no border, no forced
    equal height, and no "primary" accent strip on the first one (a
    genuine finding, not a UI selection state, doesn't need one).

    Every top finding gets SOME clear next action (Part 6): experiment-
    worthy types keep "Develop experiment"; a Performance Pattern finding
    (never experiment-worthy, by the Intelligence Agent's own classifier,
    unchanged) gets "View performance" instead of nothing, so it never
    reads as broken next to the other two.
    """
    num_col, badge_col = st.columns([0.5, 5])
    with num_col:
        st.markdown(f'<div class="ui-finding-number">{number:02d}</div>', unsafe_allow_html=True)
    with badge_col:
        ui.badge_row([finding.type.upper()])
    st.markdown(f"#### {finding.title}")
    st.write(finding.summary)
    ui.muted(finding.why_it_matters)

    st.markdown('<div style="height:0.6rem"></div>', unsafe_allow_html=True)
    action_col, develop_col = st.columns([1, 1])
    with action_col:
        with st.expander("View evidence"):
            st.caption(f"{finding.confidence.capitalize()} confidence")
            for e in finding.evidence:
                st.markdown(f"**{e.label}**")
                st.write(e.detail)
                st.caption(f"Source: {e.source}")
                if e.table is not None:
                    st.dataframe(e.table, hide_index=True, use_container_width=True)
    with develop_col:
        if finding.type in EXPERIMENT_WORTHY_TYPES:
            # Milestone 22 (Creative Lab V2, small compatibility change):
            # Creative Lab no longer opens to one selected finding's
            # experiment stage, it always shows the full Creative Plan (the
            # Strategist's synthesis of every current finding at once), so
            # this no longer needs to stash which finding was clicked.
            if st.button("Develop experiment", type="primary", key=f"develop_{finding.finding_id}"):
                st.switch_page("app_pages/creative_lab.py")
        elif finding.products:
            st.button(
                "View performance", key=f"view_perf_{finding.finding_id}",
                on_click=_jump_to_performance_patterns, args=(finding.products[0],),
            )


client = current_client()
client_id = client["client_id"]

signals = load_customer_signals(client_id)
catalog = load_creative_catalog(client_id)
joined = load_performance_with_creatives(client_id)

ui.inject_base_styles()
ui.page_header("Marketing Insights", "What is the market telling us?", badges=["Demo data"])

# --- 1. Insights Brief: the page's main content, editorial not dashboard -----
findings = generate_findings(client_id, max_findings=3)

ui.section_header("Insights Brief", f"{len(findings)} opportunit{'y' if len(findings) == 1 else 'ies'} detected from customer + performance data")

if not findings:
    ui.empty_state("No findings clear the evidence bar for the current data.")
else:
    for i, finding in enumerate(findings):
        _render_brief_item(i + 1, finding)
        if i < len(findings) - 1:
            st.divider()

st.divider()

# --- 2. Supporting analysis: secondary, never competing with the brief ------
ui.section_header("Supporting analysis", "Evidence behind the findings above.")

ui.section_header(
    "Customer language vs. current marketing",
    "Each point is a customer theme: how much of the conversation it represents, and how often "
    "current creative leads with it. Based on the full available signal history.",
    level="subsection",
)

products = sorted(catalog["product_name"].unique())
selected_landscape_product = st.selectbox(
    "Product", ["All products"] + products, key="intel_landscape_product"
)
landscape_product = None if selected_landscape_product == "All products" else selected_landscape_product
landscape = theme_coverage_landscape(signals, catalog, product=landscape_product)

if landscape.empty:
    st.caption("No comparable customer and creative data for this product.")
else:
    st.caption(
        "Reading this chart: farther right means customers discuss a theme more. Lower means current "
        "creative rarely leads with it. A theme toward the bottom right may be worth investigating as a "
        "messaging opportunity, not an automatic conclusion."
    )
    scatter = (
        alt.Chart(landscape)
        .mark_circle(size=110, color=ui.ACCENT_COLOR)
        .encode(
            x=alt.X("signal_share:Q", title="Share of customer signals", axis=alt.Axis(format=".0%")),
            y=alt.Y("primary_hook_ratio:Q", title="Share of creatives leading with theme", axis=alt.Axis(format=".0%")),
            tooltip=[
                alt.Tooltip("theme:N", title="Theme"),
                alt.Tooltip("signal_count:Q", title="Signals"),
                alt.Tooltip("signal_share:Q", title="Signal share", format=".0%"),
                alt.Tooltip("relevant_creatives:Q", title="Relevant creatives"),
                alt.Tooltip("primary_hook_count:Q", title="Leading creatives"),
                alt.Tooltip("primary_hook_ratio:Q", title="Coverage ratio", format=".0%"),
            ],
        )
    )
    labels = (
        alt.Chart(landscape)
        .mark_text(align="left", dx=9, dy=-7, fontSize=11)
        .encode(
            x="signal_share:Q",
            y="primary_hook_ratio:Q",
            text="theme:N",
        )
    )
    st.altair_chart((scatter + labels).properties(height=340), use_container_width=True)
    with st.expander("View underlying numbers"):
        st.dataframe(
            landscape[
                ["theme", "signal_count", "signal_share", "relevant_creatives", "primary_hook_count", "primary_hook_ratio"]
            ],
            hide_index=True,
            use_container_width=True,
        )

st.divider()

# --- 3. Creative performance patterns: its own clearly-headed analysis unit,
# still secondary to the Brief, but a meaningful section in its own right
# (the destination for Overview's "View performance" action) rather than a
# few loose widgets floating under the scatter chart above.
ui.section_header(
    "Creative performance patterns",
    "How different messaging approaches are performing, compared only within the same funnel stage "
    "(a BOF and a TOF creative have different economics by design, so rows are never compared across stages).",
    level="subsection",
)

with ui.card("standard"):
    perf_product = st.selectbox("Product", products, key="intel_perf_product")
    scoped = joined[joined["product_name"] == perf_product]

    if scoped.empty:
        st.caption("No performance data for this product.")
    else:
        by_style = aggregate_performance(scoped, by=["funnel_stage", "message_style"])
        by_style["message_style"] = by_style["message_style"].apply(_humanize)
        by_style["sample"] = [
            "Sufficient" if (row.spend >= PERFORMANCE_MIN_SPEND and row.purchases >= PERFORMANCE_MIN_PURCHASES) else "Limited"
            for row in by_style.itertuples()
        ]
        by_style = by_style.sort_values(["funnel_stage", "roas"], ascending=[True, False])

        # Pre-formatted as display strings rather than relying on column_config's
        # NumberColumn format, which turned out not to reliably apply once the
        # table is wrapped in a pandas Styler (see the highlighting below): the
        # format metadata reaches the frontend correctly, but real rendering
        # showed unformatted raw numbers. Formatting the values ourselves works
        # regardless, and also gets thousands separators, which the column_config
        # printf-style format string couldn't do.
        display = by_style[["funnel_stage", "message_style", "spend", "purchases", "ctr", "cpa", "roas", "sample"]].copy()
        display["spend"] = display["spend"].apply(lambda v: f"${v:,.0f}")
        display["purchases"] = display["purchases"].apply(lambda v: f"{v:,.0f}")
        display["ctr"] = display["ctr"].apply(lambda v: f"{v:.2%}")
        display["cpa"] = display["cpa"].apply(lambda v: f"${v:,.2f}")
        display["roas"] = display["roas"].apply(lambda v: f"{v:.2f}x")
        display = display.rename(
            columns={
                "funnel_stage": "Funnel stage",
                "message_style": "Message style",
                "spend": "Spend",
                "purchases": "Purchases",
                "ctr": "CTR",
                "cpa": "CPA",
                "roas": "ROAS",
                "sample": "Sample size",
            }
        )

        # Highlight only rows that clear the Intelligence Agent's own qualifying
        # bar (message_style_leaders: both ROAS and CTR ahead of every other
        # qualifying style in the same funnel stage, comfortable volume). Never
        # highlights on ROAS alone, so a "Limited" sample row is never marked.
        leading_cells = {
            (leader["funnel_stage"], _humanize(leader["leader_style"])) for leader in message_style_leaders(joined, products=[perf_product])
        }

        def _highlight_leading_row(row):
            is_leading = (row["Funnel stage"], row["Message style"]) in leading_cells
            style = "background-color: rgba(47, 111, 237, 0.14); font-weight: 600" if is_leading else ""
            return [style] * len(row)

        st.dataframe(
            display.style.apply(_highlight_leading_row, axis=1),
            hide_index=True,
            use_container_width=True,
        )
        ui.muted(
            "Highlighted rows lead their funnel stage on both ROAS and CTR with enough volume to trust the "
            'comparison. "Limited" sample rows are shown for completeness, not as a reliable pattern.'
        )
