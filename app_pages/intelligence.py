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


def _render_brief_item(number: int, finding) -> None:
    """One finding as a bounded intelligence object (Milestone 26): a quiet
    card holding an eyebrow (ordinal + category badge), the title as the
    strongest element, the summary as normal body text, a small-labeled WHY
    IT MATTERS note, and the evidence, still progressively disclosed. The
    shared rhythm card (core/ui.py) gives it the same padding and spacing
    language as Overview's compact previews, so Overview reads as the
    preview and this page as the expanded analysis. Cards establish the
    separation, so there are no dividers between findings.

    A finding is EVIDENCE, not a thing to act on (Milestone 24): it has no
    "Develop experiment"/"Develop creative"/"View performance" action. The
    only action is "View evidence"; the one path into Creative Lab is the
    single "Build Creative Plan" call to action at the very bottom of the
    page, after the supporting analysis.
    """
    with ui.card("standard", rhythm=True):
        ui.numbered_badge(number, finding.type.upper())
        ui.titled_summary(finding.title, finding.summary, "Why it matters", finding.why_it_matters)
        with st.expander("View evidence"):
            st.caption(f"{finding.confidence.capitalize()} confidence")
            for e in finding.evidence:
                ui.render_evidence_item(e.label, e.detail, e.source, e.table)


def _render_from_insight_to_creative() -> None:
    """The ONE transition from Insights into Creative Lab, placed at the very
    bottom of the page so the marketer can review the whole brief, every
    finding's evidence, AND the supporting analysis before moving on. Not
    tied to any single finding and requiring no selection. Deliberately
    calm (a plain section heading and one primary button, not a
    conversion-style banner). Uses st.button + st.switch_page (not
    st.page_link) so the page renders identically inside the multi-page app
    or in isolation.
    """
    ui.section_header(
        "From insight to creative",
        "The Creative Strategist combines these findings with customer signals, current creative coverage, "
        "and performance context to build the next creative plan.",
    )
    if st.button("Build Creative Plan", type="primary", key="build_creative_plan"):
        st.switch_page("app_pages/creative_lab.py")


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

# --- 3. From insight to creative: the single way forward, AFTER all evidence --
if findings:
    st.divider()
    _render_from_insight_to_creative()
