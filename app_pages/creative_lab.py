"""Creative Lab (Milestone 22, Creative Lab V2): turns the Strategist's
synthesis of ALL current findings into a reviewable Creative Plan, then into
one or more prepared experiments.

This replaces the earlier 3-stage, single-finding flow (Opportunity ->
Experiment -> Creatives, kept in agents/strategist/engine.py's
generate_proposal / agents/creative_studio/engine.py's
build_treatment_ad_package + generate_creative_versions, both UNTOUCHED and
still callable, just no longer this page's entry path). That model forced a
marketer to choose one Insights finding and made "find the best existing
ad" the center of the page; this page's whole point is that the Strategist
combines everything (every current finding, existing creative coverage, and
performance evidence) BEFORE a human ever chooses anything, so the choice a
marketer actually makes is "which of the Strategist's already-synthesized
concepts should we test," not "which finding do I want to explore."

All synthesis lives in agents/strategist/creative_plan.py
(build_creative_plan: one CreativeOpportunity per experiment-worthy
finding, each with 3 angle-differentiated CreativeConcepts, plus a
Performance Pattern finding folded in as cross-cutting context rather than
a family of its own); this file only renders what that layer returns and
tracks concept include/exclude selection in st.session_state. Nothing here
calls an LLM, an image provider, or any paid API: every concept is shown
through ui.render_creative_placeholder (a "Creative preview: image
generation added next" placeholder), never a generated or reused demo
asset, since live image generation for these new concepts is explicit
future work (see the Milestone 22 report). The existing live-generation
infrastructure (agents/creative_studio/generation.py, image_provider.py,
generate_creative_versions/VISUAL_DIRECTION_STRATEGIES) is untouched and
ready to be reconnected then, not deleted.

"Prepare selected experiments" can build MORE THAN ONE experiment handoff
at once (one per family with at least one included concept): see
app_pages/experiments.py, whose st.session_state["experiment_handoffs"]
became a dict keyed by proposal_id (Milestone 22) specifically so this page
never has to force every family into one combined test.
"""
import streamlit as st

from agents.creative_studio.engine import build_control_ad_package
from agents.strategist.creative_plan import CreativeFamily, CreativePlan, build_creative_plan
from agents.strategist.engine import SUCCESS_METRICS, opportunity_to_proposal
from core import ui
from core.shell import current_client


def _render_evidence(evidence_list) -> None:
    for e in evidence_list:
        st.markdown(f"**{e.label}**")
        st.write(e.detail)
        st.caption(f"Source: {e.source}")
        if e.table is not None:
            st.dataframe(e.table, hide_index=True, use_container_width=True)


def _evidence_strip_line(strip: dict) -> str:
    """The plan's real, dynamically-computed evidence counts as one quiet
    line, not a KPI dashboard: no st.metric tiles, no color, no implied
    target, just the facts the plan was built from.
    """
    return (
        f"{strip['customer_signals']} customer signals · {strip['current_creatives']} current creatives · "
        f"{strip['performance_days']} days of performance · {strip['saved_learnings']} saved experiment "
        f"learning{'s' if strip['saved_learnings'] != 1 else ''}"
    )


def _render_plan_summary(plan: CreativePlan) -> None:
    ui.section_header(
        "Creative Plan",
        "Built from customer signals, current creative coverage, campaign performance, and previous learnings.",
    )
    n_concepts = sum(len(family.concepts) for family in plan.families)
    n_families = len(plan.families)
    st.markdown(
        f"**{n_families} opportunit{'y' if n_families == 1 else 'ies'} · {n_concepts} concept"
        f"{'s' if n_concepts != 1 else ''} planned**"
    )
    ui.muted(_evidence_strip_line(plan.evidence_strip))


def _render_strategist_synthesis(plan: CreativePlan) -> None:
    ui.section_header("What the Strategist found", level="subsection")
    with ui.card("quiet"):
        ui.badge_row(["Strategist"])
        st.write(plan.strategist_summary)


def _render_cross_cutting_context(plan: CreativePlan) -> None:
    if not plan.cross_cutting_context or plan.cross_cutting_finding is None:
        return
    ui.section_header("Strategy-wide context", level="subsection")
    with ui.card("standard"):
        ui.badge_row(["Cross-cutting context", plan.cross_cutting_finding.type.upper()])
        st.write(plan.cross_cutting_context)
        with st.expander("View evidence"):
            _render_evidence(plan.cross_cutting_finding.evidence)


def _concept_include_key(concept_id: str) -> str:
    return f"clab_include_{concept_id}"


def _selected_concepts(family: CreativeFamily) -> list:
    return [c for c in family.concepts if st.session_state.get(_concept_include_key(c.concept_id), True)]


def _render_concept(concept) -> None:
    """Renders the include/exclude checkbox as render_creative_placeholder's
    own `footer`, INSIDE its bordered card, so it is the card's literal
    last element: combined with the base stylesheet's equal-height-row CSS
    (core/ui.py), this is what makes the checkbox land at the same vertical
    position across 3 concepts whose headline/primary text/rationale
    lengths differ, without truncating any of that copy or hardcoding a
    pixel height.
    """
    key = _concept_include_key(concept.concept_id)

    def _include_checkbox() -> None:
        st.checkbox("Include in experiment", value=st.session_state.get(key, True), key=key)

    ui.render_creative_placeholder(
        angle_label=concept.concept_name,
        headline=concept.headline,
        primary_text=concept.primary_text,
        cta=concept.cta,
        reason_to_believe=concept.reason_to_believe,
        why_this_exists=concept.why_this_concept_exists,
        footer=_include_checkbox,
    )


def _short_constant_phrase(constants_to_preserve: list[str]) -> str:
    return " · ".join(item.split(":", 1)[1].strip() for item in constants_to_preserve)


def _render_family(index: int, family: CreativeFamily) -> None:
    opportunity = family.opportunity
    ui.section_header(f"Creative Opportunity {index:02d} · {opportunity.pain_point}")

    with ui.card("primary"):
        ui.badge_row([f"{opportunity.product} · {opportunity.funnel_stage}"])

        st.markdown("**Why this is in the plan**")
        st.write(opportunity.why_in_plan)

        st.markdown("**Strategy**")
        strategy_cols = st.columns(3)
        with strategy_cols[0]:
            ui.muted("Avatar")
            st.write(opportunity.avatar)
        with strategy_cols[1]:
            ui.muted("Awareness stage")
            st.write(opportunity.awareness_stage)
        with strategy_cols[2]:
            ui.muted("Pain point")
            st.write(opportunity.pain_point)

        st.markdown("**What we want to learn**")
        st.write(opportunity.what_we_want_to_learn)
        ui.muted(f"Variable to test: {opportunity.variable_to_test}")
        ui.muted(f"Keeping relatively constant: {_short_constant_phrase(opportunity.constants_to_preserve)}")

        with st.expander("View evidence"):
            st.caption(f"{opportunity.confidence.capitalize()} confidence")
            _render_evidence(opportunity.evidence)

    concept_cols = st.columns(len(family.concepts))
    for col, concept in zip(concept_cols, family.concepts):
        with col:
            _render_concept(concept)


def _learning_question(opportunity) -> str:
    """The one QUESTION this experiment exists to answer (Milestone 23's
    own required "learning_question" field): built only from the
    opportunity's own already-structured fields (pain_point, product), the
    same "generic template over real structured data, never a hardcoded
    per-demo sentence" discipline every other display string in this file
    already follows. Distinct from opportunity.what_we_want_to_learn
    (carried through unchanged as the handoff's "hypothesis"): that field
    already reads as a fuller, more hypothesis-shaped sentence; this one is
    the short, plain QUESTION app_pages/experiments.py's "What we're trying
    to learn" section leads with.
    """
    return f'Which way of framing "{opportunity.pain_point}" for {opportunity.product} deserves further creative investment?'


def _build_family_handoff(client_id: str, family: CreativeFamily, selected_concepts: list) -> dict:
    """Everything app_pages/experiments.py needs for one family's proposed
    experiment: reuses build_control_ad_package as-is (via
    opportunity_to_proposal, a throwaway adapter, see agents/strategist/
    engine.py) so the reference-ad selection, its historical performance,
    and its provenance are computed exactly the same way an old-model
    experiment computed them, never re-derived here. Milestone 23: this ad
    is carried through as creative-memory/performance-reference context
    only (see app_pages/experiments.py); it is never one of the
    experiment's own arms.

    Each selected concept becomes one "creative version" entry carrying ITS
    OWN headline/primary text/CTA/proof/angle/rationale in the on_image_*
    (and, since Milestone 23, angle/why_this_concept_exists) fields, exactly
    the fields app_pages/experiments.py's comparison cards render per arm;
    image_path is None for every one of them, since Creative Lab V2 never
    calls the image provider or reuses an existing generated/demo asset for
    a new concept (core.assets.generated_asset_exists treats a None path as
    "unavailable," so Experiments shows its existing, already-correct
    "Creative unavailable" placeholder rather than crashing). Reconnecting
    live image generation for these concepts is explicit future work, not
    part of this milestone.
    """
    opportunity = family.opportunity
    proposal = opportunity_to_proposal(opportunity)
    control_ad_package = build_control_ad_package(client_id, proposal)

    representative = selected_concepts[0]
    return {
        "client_id": client_id,
        "proposal_id": opportunity.opportunity_id,
        "source_finding_id": opportunity.source_finding_id,
        "opportunity_id": opportunity.opportunity_id,
        "customer_theme": opportunity.pain_point,
        "product": opportunity.product,
        "funnel_stage": opportunity.funnel_stage,
        "avatar": opportunity.avatar,
        "awareness_stage": opportunity.awareness_stage,
        "learning_question": _learning_question(opportunity),
        "hypothesis": opportunity.what_we_want_to_learn,
        "customer_insight": opportunity.customer_insight,
        "performance_insight": opportunity.performance_insight,
        "variable_to_test": opportunity.variable_to_test,
        "constant_elements": list(opportunity.constants_to_preserve),
        "success_metrics": list(SUCCESS_METRICS),
        "control_ad_package": {
            "primary_text": control_ad_package.primary_text,
            "headline": control_ad_package.headline,
            "description": control_ad_package.description,
            "cta": control_ad_package.cta,
            "source_creative_id": control_ad_package.control_creative_id,
            "source_image_path": str(control_ad_package.control_image_path) if control_ad_package.control_image_path else None,
            "historical_performance": control_ad_package.historical_performance,
        },
        "treatment_ad_package": {
            "primary_text": representative.primary_text,
            "headline": representative.headline,
            "description": "",
            "cta": representative.cta,
            "selected_creative_versions": [
                {
                    "generated_id": concept.concept_id,
                    "concept_id": concept.concept_id,
                    "concept_name": concept.concept_name,
                    "image_path": None,
                    "visual_direction": concept.visual_direction,
                    "angle": concept.angle,
                    "why_this_concept_exists": concept.why_this_concept_exists,
                    "on_image_headline": concept.headline,
                    "on_image_supporting_copy": concept.primary_text,
                    "on_image_proof": concept.reason_to_believe,
                    "on_image_cta": concept.cta,
                }
                for concept in selected_concepts
            ],
        },
        "status": "prepared",
    }


def _prepare_selected_experiments(client_id: str, plan: CreativePlan) -> int:
    """Builds one handoff per family that has at least one included
    concept, and merges them into st.session_state["experiment_handoffs"]
    (Milestone 22: a dict keyed by proposal_id, replacing the old single
    "experiment_handoff" slot precisely so two families' proposed
    experiments can coexist without one silently overwriting the other).
    Only this client's own prior handoffs are replaced; another client's
    stay untouched. Returns how many experiments were prepared.
    """
    new_handoffs = {}
    for family in plan.families:
        selected = _selected_concepts(family)
        if not selected:
            continue
        handoff = _build_family_handoff(client_id, family, selected)
        new_handoffs[handoff["proposal_id"]] = handoff

    if new_handoffs:
        existing = st.session_state.get("experiment_handoffs", {})
        other_clients = {pid: h for pid, h in existing.items() if h.get("client_id") != client_id}
        st.session_state["experiment_handoffs"] = {**other_clients, **new_handoffs}
    return len(new_handoffs)


client = current_client()
client_id = client["client_id"]

ui.inject_base_styles()
ui.page_header("Creative Lab", "Turn market evidence into the next creative tests.", badges=["Demo data"])

plan = build_creative_plan(client_id)

_render_plan_summary(plan)
st.divider()

if not plan.families:
    ui.empty_state(
        "No creative opportunities clear the evidence bar for the current data.",
        "Check Insights once more customer signal or performance data is available.",
    )
else:
    _render_strategist_synthesis(plan)
    if plan.cross_cutting_context:
        st.divider()
        _render_cross_cutting_context(plan)
    st.divider()

    for index, family in enumerate(plan.families, start=1):
        _render_family(index, family)
        st.divider()

    ui.section_header("Prepare experiments", "Choose which concepts to test for each opportunity, then prepare an experiment.")
    any_selected = any(_selected_concepts(family) for family in plan.families)
    if st.button("Prepare selected experiments", type="primary", disabled=not any_selected):
        n_prepared = _prepare_selected_experiments(client_id, plan)
        if n_prepared:
            st.switch_page("app_pages/experiments.py")
    if not any_selected:
        st.caption("Select at least one concept in at least one opportunity to prepare an experiment.")
