"""Experiments V2 (Milestone 23): test a specific creative hypothesis,
understand what happened, and determine what the marketing team should
learn or test next. This is a product-logic redesign, not a visual pass:
the OLD page (Milestone 16.3-17C.2) was built around "current ad vs.
variants, find a winner." That model is gone from this page. Creative Lab
V2 (Milestone 22) no longer hands this page a single treatment to race
against a baseline; it hands one or more Creative Concepts, each a
distinct, purposeful way to answer ONE learning question (e.g. "which
messaging angle deserves further investment"), and this page's job is to
test those concepts against EACH OTHER, interpret what happened relative
to that question, and recommend what to investigate next, never to crown
a "winning ad."

The central loop this page exists to make obvious: Signals -> Insights ->
Creative Lab -> Experiments -> Learn -> Creative Lab again. Nothing here
closes that loop yet (no durable Save Learning: see ProposedLearning
below), but the architecture is built so a future milestone can.

Two states per prepared experiment, same as before Milestone 23:
- "prepared": what we're testing, the test setup, the concept arms as
  equal-height comparison cards, then "Run Demo Test."
- "results_pending": clicking "Run Demo Test" builds ONE deterministic
  core.experiment_simulation.ExperimentResult (via build_concept_arms_
  result: every selected concept becomes its own arm; there is NO
  mandatory current-ad arm) AND immediately runs the Performance Agent
  (agents.performance.engine.analyze_concept_experiment) against it, in
  the same click. The results view answers 4 questions in order: what did
  we test, what happened, what did we learn, what should we test next.

An existing Brio ad (Creative Lab's own deterministic, same-product/
same-funnel-stage reference-ad selection, unchanged: agents.strategist.
engine.select_control_creative) is carried through the handoff as
control_ad_package and reused here ONLY to anchor realistic, comparable
synthetic performance for every arm (core.experiment_simulation.
build_concept_arms_result's own reference-anchor discipline) and, quietly,
as creative-memory/performance context in "View experiment details." It
is never rendered as a competing arm, never called "control" in this
page's own text, and never presented as though beating it were the point.

The OLD current-ad-vs-treatments infrastructure this page used to render
(core.experiment_simulation.build_experiment_result, agents.performance.
engine.analyze_experiment/ExperimentAnalysis/CreativeAnalysis, agents.
strategist.engine.select_control_creative) is UNCHANGED and still fully
callable: kept for a future experiment type that genuinely has a baseline
to test against, just no longer what this page renders by default.

Every prepared experiment (Creative Lab can prepare more than one; see
st.session_state["experiment_handoffs"], a dict keyed by proposal_id,
Milestone 22) gets its own tab, labeled by its human-readable customer
theme, never a technical id. Each tab's prepared/result/decision state
lives in its own per-proposal_id slot (experiment_handoffs itself,
st.session_state["experiment_results"], ["experiment_analyses"]), so
running or resetting one experiment never touches another.

Nothing here calls the image provider, an LLM, or any paid API, or writes
to a dataset file: Run Demo Test's "decision" is a proposed, in-session-
only ProposedLearning (status="pending_review"), never a write to
clients/<client>/approved_learnings.json, which stays a future,
human-approved step. Concept arms have no image (image_path is always
None: Creative Lab V2 never generates or reuses one for a concept this
milestone) and render through ui.render_creative_placeholder, the same
"Creative preview: image generation added next" placeholder Creative Lab
itself uses, never a generated or reused demo asset.
"""
import streamlit as st

from agents.performance.engine import (
    EVIDENCE_STRENGTH_LABELS,
    ConceptExperimentAnalysis,
    analyze_concept_experiment,
)
from core import ui
from core.experiment_simulation import ExperimentResult, build_concept_arms_result
from core.shell import current_client

_ARM_LETTERS = "ABCDEFGH"

_KEEPING_CONSISTENT_LINE = "Product · Audience · Funnel stage · Format · CTA · Core product proof"


def _arm_letter(index: int) -> str:
    return _ARM_LETTERS[index] if index < len(_ARM_LETTERS) else str(index + 1)


def _prepared_description(handoff: dict) -> str:
    n = len(handoff["treatment_ad_package"]["selected_creative_versions"])
    theme = handoff["customer_theme"].lower()
    noun = "way" if n == 1 else "ways"
    return f"We're testing {n} {noun} of framing the {theme} problem to learn which direction deserves further creative development."


def _render_learning_question(handoff: dict) -> None:
    ui.section_header("What we're trying to learn")
    st.write(handoff.get("learning_question") or handoff["hypothesis"])
    ui.muted("Hypothesis")
    st.caption(handoff["hypothesis"])


def _render_test_setup(handoff: dict) -> None:
    """A clean, compact section, deliberately not a technical configuration
    panel: just enough for a marketing leader to see WHY the comparison is
    meaningful. Every value comes from the handoff Creative Lab already
    built (opportunity.product/funnel_stage/avatar, the shared
    "Messaging angle" variable, the existing ROAS-primary/CTR-CPA-
    Purchases-secondary convention this app has used since Milestone 16.3);
    nothing here is recomputed or invented.
    """
    ui.section_header("Test setup")
    with ui.card("standard"):
        c1, c2, c3 = st.columns(3)
        with c1:
            ui.muted("Product")
            st.write(handoff.get("product") or "Not specified")
        with c2:
            ui.muted("Audience")
            st.write(handoff.get("avatar", "Not specified"))
        with c3:
            ui.muted("Funnel stage")
            st.write(handoff.get("funnel_stage", "Not specified"))

        c4, c5, c6 = st.columns(3)
        with c4:
            ui.muted("Variable")
            st.write("Messaging angle")
        with c5:
            ui.muted("Primary metric")
            st.write("ROAS")
        with c6:
            ui.muted("Supporting metrics")
            st.write("CTR · CPA · Purchases")

        ui.muted("Keeping consistent")
        st.write(_KEEPING_CONSISTENT_LINE)


def _render_arm_card(index: int, arm: dict) -> None:
    ui.render_creative_placeholder(
        angle_label=f"{_arm_letter(index)} · {arm['concept_name']}",
        headline=arm["on_image_headline"],
        primary_text=arm["on_image_supporting_copy"],
        cta=arm["on_image_cta"],
        reason_to_believe=arm.get("on_image_proof", ""),
        why_this_exists=arm.get("why_this_concept_exists", ""),
    )


def _render_arms_grid(arms: list[dict]) -> None:
    """Equal-height comparison cards, the same shared row layout Creative
    Lab's own concept row uses (core/ui.py's stretch/flex CSS, scoped to
    ANY row of bordered cards, not something reimplemented here): a
    deliberate side-by-side comparison, never uneven boxes.
    """
    cols = st.columns(len(arms))
    for col, (index, arm) in zip(cols, enumerate(arms)):
        with col:
            _render_arm_card(index, arm)


def _render_experiment_details(handoff: dict) -> None:
    """Progressive disclosure for the technical/traceability details a
    marketer doesn't need up front: ids, full constants list, each arm's
    own strategic angle, and the existing ad used only as creative-memory/
    performance context (never shown as a competing arm, never called
    "control" here).
    """
    with st.expander("View experiment details"):
        st.caption(f"Opportunity id: {handoff['opportunity_id']}")
        st.caption(f"Source finding: {handoff['source_finding_id']}")
        st.caption(f"Variable tested: {handoff['variable_to_test']}")
        st.markdown("**Keep consistent (full):**")
        for item in handoff["constant_elements"]:
            st.markdown(f"- {item}")

        st.markdown("**Concept arms:**")
        for index, arm in enumerate(handoff["treatment_ad_package"]["selected_creative_versions"]):
            st.markdown(f"- **{_arm_letter(index)} · {arm['concept_name']}**: {arm.get('angle', '')}")
            if arm.get("why_this_concept_exists"):
                st.caption(arm["why_this_concept_exists"])

        reference_ad = handoff.get("control_ad_package", {})
        if reference_ad.get("headline"):
            st.markdown("**Creative memory / performance reference (not a tested arm):**")
            st.caption(
                f'"{reference_ad["headline"]}" is an existing ad for this product and funnel stage, used only to '
                "anchor realistic, comparable synthetic performance for this test."
            )
            perf = reference_ad.get("historical_performance")
            if perf:
                ui.metric_row([("Historical ROAS", f"{perf['roas']:.2f}x"), ("Historical CTR", f"{perf['ctr']:.2%}")])
                ui.muted("Demo synthetic historical performance, shown as context only.")


def _run_demo_test(client_id: str, handoff: dict) -> None:
    """The "Run Demo Test" button's on_click callback. Streamlit runs a
    button's on_click callback BEFORE the script re-renders, so the fresh
    "results_pending" status, the new result, AND its analysis are all
    already in place by the time the script body runs again on the same
    click; no explicit st.rerun() needed. Keyed by this handoff's own
    proposal_id (Milestone 22/23), so two prepared experiments never share
    one result/analysis slot.
    """
    result = build_concept_arms_result(client_id, handoff)
    proposal_id = handoff["proposal_id"]
    st.session_state.setdefault("experiment_results", {})[proposal_id] = result
    st.session_state.setdefault("experiment_analyses", {})[proposal_id] = analyze_concept_experiment(handoff, result)
    handoff["status"] = "results_pending"


def _reset_demo_test(handoff: dict) -> None:
    """"Reset Demo Test"'s on_click callback: clears the stored result and
    analysis for THIS experiment only, returning to the prepared view; the
    handoff itself (selected concepts, everything Creative Lab built) is
    untouched, so running the demo test again reproduces the exact same
    deterministic result and analysis. Keyed by proposal_id, same
    reasoning as _run_demo_test: resetting one experiment never touches
    another prepared experiment's state.
    """
    handoff["status"] = "prepared"
    proposal_id = handoff["proposal_id"]
    st.session_state.get("experiment_results", {}).pop(proposal_id, None)
    st.session_state.get("experiment_analyses", {}).pop(proposal_id, None)


def _render_prepared_view(client_id: str, handoff: dict) -> None:
    ui.muted(handoff["customer_theme"].upper())
    st.title(f"{handoff['customer_theme'].title()} messaging test")
    ui.badge_row(["Ready to test"])
    st.write(_prepared_description(handoff))

    st.divider()

    _render_learning_question(handoff)

    st.divider()

    _render_test_setup(handoff)

    st.divider()

    ui.section_header("Creatives in this test")
    arms = handoff["treatment_ad_package"]["selected_creative_versions"]
    _render_arms_grid(arms)

    _render_experiment_details(handoff)

    st.divider()

    ui.section_header("Ready to test")
    st.write(
        "These concepts are designed to primarily compare messaging angle while keeping the product, audience, "
        "funnel context, format, and CTA consistent."
    )
    _, action_col, _ = st.columns([1, 1, 1])
    with action_col:
        st.button(
            "Run Demo Test", type="primary", use_container_width=True, key=f"run_demo_test_{handoff['proposal_id']}",
            on_click=_run_demo_test, args=(client_id, handoff),
        )
        st.caption("Demo test uses deterministic synthetic performance data.")


def _render_results_hero(handoff: dict, analysis: ConceptExperimentAnalysis) -> None:
    """Answers "what did we test?" (one compact recap line, not a repeat of
    the full Test Setup panel) and "what happened?" (the Performance
    Agent's own headline, evidence-tied, never "proven"/"winner").
    """
    ui.badge_row(["Results", "Demo synthetic results"])
    st.title(f"{handoff['customer_theme'].title()} messaging test")
    ui.muted(f"What we tested: {analysis.learning_question}")

    with ui.card("primary"):
        st.subheader(analysis.headline)
        st.markdown(f"**Evidence:** {EVIDENCE_STRENGTH_LABELS.get(analysis.evidence_strength, analysis.evidence_strength)}")
        st.caption(analysis.evidence_strength_reason)


def _render_arms_comparison(result: ExperimentResult, analysis: ConceptExperimentAnalysis) -> None:
    """"What did we learn from it," part 1: every arm side by side, named
    by its own concept name (never "Treatment 1/2/3"), ROAS/CTR/CPA/
    Purchases aligned in the same columns down every row, a bare neutral
    arrow for a real (non-noise) move relative to the GROUP'S OWN MEAN,
    never a color, never a claim of significance. No current-ad row: this
    experiment type has none.
    """
    ca_by_id = {ca.concept_id: ca for ca in analysis.arm_analyses}

    with ui.card("standard"):
        header = st.columns([2, 1, 1, 1, 1])
        for col, label in zip(header, ["Concept", "ROAS", "CTR", "CPA", "Purchases"]):
            col.caption(label)
        st.divider()

        for arm in result.treatment_results:
            ca = ca_by_id.get(arm.creative_id)
            row = st.columns([2, 1, 1, 1, 1])
            with row[0]:
                st.markdown(f"**{arm.name}**")
                if ca:
                    st.caption(ca.interpretation.split(".")[0] + ".")
            row[1].write(f"{arm.roas:.2f}x" if arm.roas is not None else "N/A")
            row[2].write(f"{arm.ctr:.2%}" if arm.ctr is not None else "N/A")
            row[3].write(f"${arm.cpa:,.2f}" if arm.cpa is not None else "N/A")
            row[4].write(f"{arm.purchases:,}")

    ui.muted("Each concept is compared against this test's own group average, not against an existing ad.")


def _render_learning(analysis: ConceptExperimentAnalysis) -> None:
    """"What did we learn," part 2: the Performance Agent's interpretation
    tied explicitly back to the original learning question, plus its
    limitations, stated once, plainly.
    """
    ui.section_header("What we learned")
    with ui.card("standard"):
        st.write(analysis.learning_statement)
        ui.muted(analysis.limitations)


def _render_next_test(analysis: ConceptExperimentAnalysis) -> None:
    """"What should we test next": a recommended LEARNING QUESTION, never
    an autonomous action and never "scale the winner." Also surfaces the
    ProposedLearning as a clearly-labeled, pending-review, in-session-only
    object: this is what a future Save Learning step would promote, not
    something this page ever writes to approved_learnings.json itself.
    """
    ui.section_header("What should we test next?")
    next_test = analysis.recommended_next_test
    with ui.card("primary"):
        st.markdown(f"**{next_test.label}**")
        st.write(next_test.rationale)

    with ui.card("quiet"):
        ui.badge_row(["Proposed learning", "Pending review"])
        st.write(analysis.learning_statement)
        ui.muted(
            "This is a proposed learning, not an approved one: a human would need to review and approve it "
            "before it durably informs future Creative Plans."
        )


def _render_results_view(client_id: str, handoff: dict, result: ExperimentResult, analysis: ConceptExperimentAnalysis) -> None:
    """The results state: fully replaces the prepared view. Answers, in
    order: what did we test, what happened, what did we learn, what should
    we test next (this milestone's own explicit page hierarchy).
    """
    _render_results_hero(handoff, analysis)
    _render_arms_comparison(result, analysis)
    _render_learning(analysis)
    _render_next_test(analysis)

    _render_experiment_details(handoff)
    st.button("Reset Demo Test", on_click=_reset_demo_test, args=(handoff,), key=f"reset_{handoff['proposal_id']}")


def _render_experiment(client_id: str, handoff: dict) -> None:
    status = handoff.setdefault("status", "prepared")
    proposal_id = handoff["proposal_id"]

    result = st.session_state.get("experiment_results", {}).get(proposal_id) if status == "results_pending" else None
    analysis = st.session_state.get("experiment_analyses", {}).get(proposal_id) if status == "results_pending" else None
    if status == "results_pending" and result is not None and analysis is not None:
        _render_results_view(client_id, handoff, result, analysis)
    else:
        if status == "results_pending":
            # A results_pending status with no matching result/analysis
            # shouldn't happen through normal use (the button that sets
            # status also builds both in the same click), but never crash
            # on it: fall back to the prepared view rather than showing a
            # broken results page.
            handoff["status"] = "prepared"
        _render_prepared_view(client_id, handoff)


client = current_client()
client_id = client["client_id"]

# Milestone 22/23: Creative Lab V2 can prepare more than one experiment at
# once (one per Creative Opportunity), so a single "experiment_handoff" slot
# became a dict of handoffs keyed by their own proposal_id. Scoped to the
# current client only, same as every other page-level dataset here.
handoffs = {
    proposal_id: h
    for proposal_id, h in st.session_state.get("experiment_handoffs", {}).items()
    if h.get("client_id") == client_id
}

ui.inject_base_styles()

if not handoffs:
    ui.page_header("Experiments", "Test creative ideas and turn the results into learnings.")
    ui.empty_state("No experiment prepared yet.", "Review the Creative Plan in Creative Lab and prepare at least one experiment.")
    if st.button("Go to Creative Lab", type="primary"):
        st.switch_page("app_pages/creative_lab.py")
else:
    ordered_ids = list(handoffs.keys())
    n = len(ordered_ids)
    ui.page_header("Experiments", "Test creative ideas and turn the results into learnings.")
    st.caption(f"{n} experiment{'s' if n != 1 else ''} ready")

    if n > 1:
        # Milestone 23: a human-readable tab per experiment (never a
        # technical id selector), Streamlit's own native way to give each
        # experiment fully independent visual space while keeping all of
        # them one click away; each tab reads/writes only its OWN
        # proposal_id-keyed state, so running or resetting one can never
        # affect another (Streamlit preserves which tab is active across a
        # rerun on its own, no extra session-state bookkeeping needed).
        tab_labels = [handoffs[pid]["customer_theme"].title() for pid in ordered_ids]
        tabs = st.tabs(tab_labels)
        for proposal_id, tab in zip(ordered_ids, tabs):
            with tab:
                _render_experiment(client_id, handoffs[proposal_id])
    else:
        _render_experiment(client_id, handoffs[ordered_ids[0]])
