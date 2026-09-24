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
a creative opportunity of its own); this file renders that plan and manages
generation and selection state in st.session_state.

Milestone 28 (Creative Studio V3): each concept becomes a FINISHED ad. An
explicit, per-opportunity "Generate creatives" action (live mode only) runs
agents/creative_studio/pipeline.py: a validated AdExecutionSpec (copy as
data) and then the image. Nothing generates on render or rerun; generation
state is kept per concept in st.session_state["clab_creatives"] and
rebuilt from what is saved on disk (creative_store), so a checkbox, an
expander or another concept's click never spends money; a concept that is
already generated is never re-queued except by its own explicit Regenerate
(which writes a new version); one concept's failure never affects another.
Milestone 28.1 keeps three concepts deliberately separate, so they can never
be conflated: (A) the CREATIVE PLAN (opportunities, strategy, learning
questions, concepts) exists before any generation and is identical in every
mode; (B) UI GENERATION STATE (idle/pending/ready/failed/unavailable, kept
per concept in st.session_state["clab_creatives"]) is what the marketer
actually sees, and in demo mode ALWAYS starts idle for a fresh session
regardless of what is on disk; (C) the six cached outputs on disk
(assets/<client>/demo_playback_manifest.json, agents/creative_studio/
demo_playback.py) only ever answer "which output should demo mode return if
asked to generate this concept," never "has the marketer generated this
concept yet." Clicking "Generate creatives" walks a short multi-step status
(never a provider call; see _process_pending_demo) before revealing those
outputs, and every "unavailable"/failure state is worded identically to a
real live failure: nothing about this page's own text should let a marketer
tell demo mode apart from a fresh live run. Nothing is included in an
experiment by default: the marketer explicitly includes finished ads, and
"Prepare selected experiments" hands Experiments the EXACT generated asset
ids/paths and copy (see _arm_from_creative); Experiments never regenerates or
rewrites them. Milestone 28.4: an idle concept renders as a creative
DIRECTION/brief (ui.render_creative_brief: angle name, strategic idea, why
it's worth exploring), never as an ad-shaped card; only a "ready" concept
renders as a real ad (ui.render_generated_ad), so the two states are
visually unmistakable, not just differently worded.

"Prepare selected experiments" can build MORE THAN ONE experiment handoff
at once (one per opportunity with at least one included ad): see
app_pages/experiments.py, whose st.session_state["experiment_handoffs"]
is a dict keyed by proposal_id so no opportunity is forced into one
combined test.
"""
import time
from pathlib import Path

import streamlit as st

import agents.creative_studio.demo_playback as demo_playback
import agents.creative_studio.pipeline as pipeline
from agents.creative_studio.creative_store import plan_fingerprint
from agents.creative_studio.engine import build_control_ad_package
from agents.creative_studio.execution import ExecutionSpecError, TextGenerationError, learning_question_for
from agents.creative_studio.generation import (
    CREATIVE_GENERATION_MODE_LIVE,
    creative_generation_mode,
    creative_generation_ready,
)
from agents.creative_studio.image_provider import ImageGenerationError
from agents.strategist.creative_plan import CreativeFamily, CreativePlan, build_creative_plan
from agents.strategist.engine import SUCCESS_METRICS, opportunity_to_proposal
from core import ui
from core.assets import generated_asset_exists
from core.shell import current_client


def _render_evidence(evidence_list) -> None:
    for e in evidence_list:
        ui.render_evidence_item(e.label, e.detail, e.source, e.table)


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
    """One compact orientation line before the plan itself (Milestone 29):
    replaces the old separate "Creative Plan" section header + its own
    explanatory subtitle + a bold opportunity/concept count + a muted
    evidence-strip line - four stacked typographic levels all announcing
    that a Creative Plan exists, which the page's own title and the plan
    content right below it already make obvious. Carries exactly the same
    real counts (nothing added, nothing dropped: reuses
    _evidence_strip_line unchanged), just as one quiet line rather than a
    small header section of its own, so it never competes with the actual
    creative strategy and the first Creative Opportunity appears sooner.
    """
    n_concepts = sum(len(family.concepts) for family in plan.families)
    n_families = len(plan.families)
    ui.muted(
        f"{n_families} opportunit{'y' if n_families == 1 else 'ies'} · {n_concepts} concept"
        f"{'s' if n_concepts != 1 else ''} planned · {_evidence_strip_line(plan.evidence_strip)}"
    )


def _render_strategist_synthesis(plan: CreativePlan) -> None:
    """Milestone 31: shown as labeled blocks (ui.insight_blocks) instead of
    one paragraph that ran the actual plan straight into an unrelated
    tone-context aside. Same two pieces plan.strategist_summary already
    joins into one string (plan.strategist_summary_parts), just visually
    separated; the second block is simply skipped (insight_blocks' own
    behavior) on the rare plan with no cross-cutting finding to note.
    """
    ui.section_header("What the Strategist found", level="subsection")
    with ui.card("quiet"):
        ui.badge_row(["Strategist"])
        plan_line, aside = plan.strategist_summary_parts
        ui.insight_blocks([("What we're seeing", plan_line), ("Also worth noting", aside)])


def _render_cross_cutting_context(plan: CreativePlan) -> None:
    """Milestone 31: shown as labeled blocks instead of one paragraph that
    used to state the same statistic twice before explaining the travel
    rule. Same two pieces plan.cross_cutting_context already joins into one
    string (plan.cross_cutting_context_parts), just visually separated.
    """
    if not plan.cross_cutting_context_parts or plan.cross_cutting_finding is None:
        return
    ui.section_header("Strategy-wide context", level="subsection")
    with ui.card("standard"):
        ui.badge_row(["Cross-cutting context", plan.cross_cutting_finding.type.upper()])
        what_we_see, how_we_use_it = plan.cross_cutting_context_parts
        ui.insight_blocks([("What we're seeing", what_we_see), ("How we're using it", how_we_use_it)])
        with st.expander("View evidence"):
            _render_evidence(plan.cross_cutting_finding.evidence)


STATE_KEY = "clab_creatives"


def _concept_include_key(concept_id: str) -> str:
    return f"clab_include_{concept_id}"


def _slots() -> dict:
    return st.session_state.setdefault(STATE_KEY, {})


def _slot_for(client_id: str, family: CreativeFamily, concept) -> dict:
    """The per-concept generation state, kept in session state so it survives
    every ordinary Streamlit rerun (a checkbox, an expander, another
    concept's click) without any provider call. status: idle | pending |
    ready | failed | unavailable. `creative` is the currently selected
    version; `versions` is every saved version; `spec` caches a validated
    AdExecutionSpec whose IMAGE step failed, so a retry does not pay for the
    text step again.

    In LIVE mode, a fresh slot is (re)built from what is already saved on
    disk (disk reads only): a concept already generated in an earlier
    session starts "ready", exactly as before this milestone. In DEMO mode
    (Milestone 28), a fresh slot ALWAYS starts "idle" regardless of what is
    saved: the six demo playback assets exist on disk, but this page must
    look ready-to-generate on open, and reveal them only after the marketer
    explicitly clicks "Generate creatives" (see _process_pending_demo).
    """
    slots = _slots()
    fingerprint = plan_fingerprint(family.opportunity, concept)
    slot = slots.get(concept.concept_id)
    if slot is None or slot["fingerprint"] != fingerprint:
        if creative_generation_mode() == CREATIVE_GENERATION_MODE_LIVE:
            versions = pipeline.saved_versions(client_id, family.opportunity, concept)
            slot = {
                "fingerprint": fingerprint,
                "status": "ready" if versions else "idle",
                "versions": versions,
                "creative": versions[-1] if versions else None,
                "spec": None,
                "error": None,
                "force": False,
            }
        else:
            slot = {
                "fingerprint": fingerprint,
                "status": "idle",
                "versions": [],
                "creative": None,
                "spec": None,
                "error": None,
                "force": False,
            }
        slots[concept.concept_id] = slot
    return slot


def _reset_demo_reveal_state() -> None:
    """Demo-mode-only, on_click callback: returns Creative Lab's own
    PRESENTATION state to "nothing generated yet" for every opportunity, so
    the demo can be replayed from a clean start. Clears only session state
    (the concept slots and their include checkboxes); never touches a
    generated asset, its metadata, an already-prepared experiment, or
    approved_learnings.json, and calls no provider.
    """
    st.session_state.pop(STATE_KEY, None)
    for key in [k for k in st.session_state if k.startswith("clab_include_")]:
        del st.session_state[key]


def _request_generation(concept_ids: list[str], force: bool = False) -> None:
    """on_click callback behind every generate/retry/regenerate button. It
    only MARKS concepts pending (cheap, no provider call); generation itself
    runs once, after the page has rendered, in _process_pending. A concept
    that is already pending is never re-marked, and a ready concept is only
    re-marked by an explicit force (Regenerate), so repeated clicks and
    reruns cannot queue duplicate work.
    """
    slots = _slots()
    for concept_id in concept_ids:
        slot = slots.get(concept_id)
        if slot is None or slot["status"] == "pending":
            continue
        if slot["status"] == "ready" and not force:
            continue
        slot["status"] = "pending"
        slot["force"] = force
        slot["error"] = None
        if force:
            slot["spec"] = None


def _fail(slot: dict, message: str, status: str = "failed") -> None:
    """Record a failure for ONE concept without touching any other. If the
    concept already had a good version (a failed Regenerate), that version
    stays selected and usable; the message is kept as a notice. `status`
    lets demo playback record "unavailable" (a missing/mismatched saved
    asset) distinctly from "failed" (a live provider error), so the card's
    wording never implies an API failure that did not happen.
    """
    slot["force"] = False
    slot["error"] = message
    slot["status"] = "ready" if slot.get("creative") is not None else status


def _selected_creatives(family: CreativeFamily) -> list[tuple]:
    """(concept, current GeneratedCreative) for every concept the marketer
    has explicitly included. A concept only counts if it has a finished
    creative whose image file still exists; nothing is ever included by
    default and nothing ungenerated can be included.
    """
    chosen = []
    for concept in family.concepts:
        slot = _slots().get(concept.concept_id)
        if not slot or slot["status"] != "ready" or slot["creative"] is None:
            continue
        if not generated_asset_exists(slot["creative"].image_path):
            continue
        if st.session_state.get(_concept_include_key(concept.concept_id), False):
            chosen.append((concept, slot["creative"]))
    return chosen


def _render_concept(client_id: str, family: CreativeFamily, concept) -> None:
    """One concept card in its current generation state. Every state ends
    with the same include checkbox as the card's own last element (so it
    aligns across the row).

    Milestone 28.9: the checkbox is checked BY DEFAULT once a concept
    reaches "ready", and the marketer can still uncheck any of them. This
    relies on Streamlit's own widget semantics rather than any bookkeeping:
    `st.checkbox(..., value=X, key=K)` only ever uses `value` to seed
    st.session_state[K] the very FIRST time key K is created; every later
    call with the same key, in this run or any future rerun, is a no-op as
    far as `value` is concerned - the widget just reflects whatever is
    already in session_state (the marketer's own last choice).

    That guarantee only holds if the widget is actually instantiated on
    EVERY run once it exists: Streamlit drops a widget's session_state entry
    for any run where that widget's call is skipped entirely, so the
    checkbox must render on every run from a concept's first "ready" onward,
    never conditionally omitted, or a later run recreating it would look
    like a fresh widget and re-apply value=True over a manual uncheck. So it
    renders whenever `status == "ready"`, AND during "pending" once
    `creative is not None` (Regenerate: the concept was already ready, still
    holds its PREVIOUS creative while the new one generates, per
    _request_generation/_process_pending_live - the checkbox must keep
    rendering through that transient window too). It is never rendered for
    idle/first-time-pending/failed/unavailable, where `creative is None`:
    that first "ready" (or first successful Retry) is always the key's
    genuine first-ever creation, so `value=True` correctly initializes it
    checked. Reset Demo already deletes every "clab_include_*" key
    (_reset_demo_reveal_state), so the next generation's first "ready"
    render is again a first-ever creation and initializes checked again.
    """
    slot = _slot_for(client_id, family, concept)
    status = slot["status"]
    creative = slot["creative"]
    include_key = _concept_include_key(concept.concept_id)
    cid = concept.concept_id

    demo_mode = creative_generation_mode() != CREATIVE_GENERATION_MODE_LIVE

    def _footer() -> None:
        if status in ("failed", "unavailable"):
            st.button("Retry", key=f"clab_retry_{cid}", on_click=_request_generation, args=([cid], False))
        elif status == "ready" and not demo_mode:
            st.button("Regenerate", key=f"clab_regen_{cid}", on_click=_request_generation, args=([cid], True))
        if status == "ready" or (status == "pending" and creative is not None):
            st.checkbox("Include in experiment", value=True, key=include_key)

    if status == "ready" and creative is not None and creative.ad_spec is not None:
        spec = creative.ad_spec
        label = concept.concept_name + (f" · v{creative.version}" if not demo_mode and len(slot["versions"]) > 1 else "")
        ui.render_generated_ad(
            angle_label=label,
            image_path=str(creative.image_path),
            primary_text=spec.primary_text,
            headline=spec.meta_headline,
            description=spec.description,
            cta=spec.cta,
            why_this_exists=(f"{spec.why_this_concept_exists}"),
            footer=_footer,
        )
        if slot["error"]:
            st.caption(f"The last regeneration did not complete, so this version is unchanged. {slot['error']}")
        return

    if status == "pending":
        ui.render_creative_placeholder(
            angle_label=concept.concept_name, box_title="GENERATING", box_subtitle="This can take a minute",
            primary_text=concept.angle, why_this_exists=concept.why_this_concept_exists, footer=_footer,
        )
    elif status == "failed":
        ui.render_creative_placeholder(
            angle_label=concept.concept_name, box_title="GENERATION FAILED", box_subtitle="Nothing was saved for this concept",
            primary_text=concept.angle, note=slot["error"] or "", why_this_exists=concept.why_this_concept_exists, footer=_footer,
        )
    elif status == "unavailable":
        # Deliberately worded and titled IDENTICALLY to the live "failed"
        # card above: from the marketer's side this must be indistinguishable
        # from a real generation hiccup. slot["error"] (the real, specific
        # demo_playback.DemoPlaybackUnavailable reason) is kept internally
        # for troubleshooting a broken demo asset before a presentation, but
        # is never rendered here.
        ui.render_creative_placeholder(
            angle_label=concept.concept_name, box_title="GENERATION FAILED", box_subtitle="Nothing was saved for this concept",
            primary_text=concept.angle, note="Something went wrong generating this concept. Try again.",
            why_this_exists=concept.why_this_concept_exists, footer=_footer,
        )
    else:
        # Milestone 28.4: a concept with no finished ad yet is presented as a
        # CREATIVE DIRECTION / BRIEF, not as a near-finished ad missing only
        # its photo. Two prior passes (28.2's "AD NOT GENERATED YET" box and
        # 28.3's restored render_creative_placeholder, headline/body copy/CTA
        # pill included) both kept the same ad-shaped card - a badge, an
        # image-shaped box, a headline, a paragraph, a CTA button - which
        # reads as "this ad basically exists" no matter what the box says.
        # ui.render_creative_brief shares no visual language with an ad card
        # at all: just the angle name plus the concept's own real strategy
        # fields (`angle`, `why_this_concept_exists`); no image slot, no CTA,
        # no Include-in-experiment control (nothing exists yet to include).
        ui.render_creative_brief(
            angle_label=concept.concept_name,
            strategic_idea=concept.angle,
            why_this_exists=concept.why_this_concept_exists,
        )


def _render_generation_controls(client_id: str, family: CreativeFamily) -> None:
    """The one deliberate way to spend money (live mode) or to advance the
    demo (demo mode): an explicit, per-opportunity action. Never runs on
    render; disabled while anything is pending.

    Milestone 28.1: in demo mode, once every concept is ready, this row
    renders NOTHING at all (not even a disabled button): the section is
    meant to visually move forward into review, the marketer's actual next
    task, rather than leave a spent action sitting on the page. Live mode
    keeps showing a disabled button plus a Regenerate hint, since live
    Regenerate is a real, still-available action there.
    """
    slots = [_slot_for(client_id, family, c) for c in family.concepts]
    todo = [c.concept_id for c, slot in zip(family.concepts, slots) if slot["status"] in ("idle", "failed", "unavailable")]
    busy = any(slot["status"] == "pending" for slot in slots)

    if creative_generation_mode() != CREATIVE_GENERATION_MODE_LIVE:
        if not todo and not busy:
            return
        st.button(
            "Generate creatives", type="primary", key=f"clab_generate_{family.opportunity.opportunity_id}",
            disabled=busy or not todo, on_click=_request_generation, args=(todo, False),
        )
        st.caption(
            "Generates a finished ad for each concept below (image, primary text, headline, description, CTA). "
            "It runs only when you click, and never repeats a concept that already succeeded."
        )
        return

    if not creative_generation_ready():
        st.warning("Live creative generation is unavailable: OPENAI_API_KEY is not set. See README for setup.")
        return
    st.button(
        "Generate creatives", type="primary", key=f"clab_generate_{family.opportunity.opportunity_id}",
        disabled=busy or not todo, on_click=_request_generation, args=(todo, False),
    )
    st.caption(
        "Generates a finished ad for each concept below (image, primary text, headline, description, CTA). "
        "It runs only when you click, and never repeats a concept that already succeeded."
        if todo
        else "All concepts in this opportunity are generated. Use Regenerate on a card to make a new version."
    )


def _render_generation_details(family: CreativeFamily) -> None:
    ready = [(c, _slots()[c.concept_id]) for c in family.concepts if _slots().get(c.concept_id, {}).get("status") == "ready"]
    if not ready:
        return
    with st.expander("Generation details"):
        for concept, slot in ready:
            creative = slot["creative"]
            versions_known = len(slot["versions"])
            title = f"**{concept.concept_name}**" + (f" (version {creative.version} of {versions_known})" if versions_known > 1 else "")
            st.markdown(title)
            st.caption(f"{creative.provider} · {creative.model} · {creative.generated_at}")
            if creative.reference_asset_paths:
                st.caption("Reference: " + ", ".join(Path(p).name for p in creative.reference_asset_paths))
            else:
                st.caption("No reference image was used.")
            st.code(creative.prompt, language=None)


DEMO_REVEAL_DELAY_SECONDS = 2.5


def _process_pending_live(client_id: str, plan: CreativePlan, work: list, slots: dict) -> None:
    """LIVE mode only: resolves providers once, then generates each pending
    concept. Each concept is independent, so one failure never affects
    another's success, and a concept whose spec is already cached (an
    image-step retry) skips the text step.
    """
    with st.spinner("Generating creatives. This runs once per concept."):
        try:
            text_provider, image_provider = pipeline.get_providers()
        except (TextGenerationError, ImageGenerationError) as exc:
            for _, concept in work:
                _fail(slots[concept.concept_id], str(exc))
            text_provider = image_provider = None
        if text_provider is not None:
            for family, concept in work:
                slot = slots[concept.concept_id]
                accepted = []
                for other in family.concepts:
                    o = slots.get(other.concept_id)
                    if other.concept_id != concept.concept_id and o and o["status"] == "ready" and o["creative"] and o["creative"].ad_spec:
                        accepted.append(o["creative"].ad_spec)
                try:
                    creative = pipeline.produce_creative(
                        client_id, family.opportunity, concept, family.concepts, text_provider, image_provider,
                        performance_context=plan.cross_cutting_context or "",
                        spec=None if slot["force"] else slot["spec"],
                        accepted_specs=accepted,
                        force=slot["force"],
                        on_spec=lambda spec, s=slot: s.__setitem__("spec", spec),
                    )
                    slot.update(
                        status="ready", creative=creative, error=None, force=False, spec=None,
                        versions=pipeline.saved_versions(client_id, family.opportunity, concept),
                    )
                except (ExecutionSpecError, TextGenerationError, ImageGenerationError) as exc:
                    _fail(slot, str(exc))
                except Exception:
                    _fail(slot, "Something went wrong generating this creative. Try again.")


def _process_pending_demo(client_id: str, work: list, slots: dict) -> None:
    """DEMO MODE ONLY (Milestone 28, presentation corrected in 28.1).
    Structurally cannot call a provider: this function never imports or
    calls agents.creative_studio.pipeline, text_provider, or
    image_provider (see agents/creative_studio/demo_playback.py's own
    module-level guarantee), regardless of `force`.

    From the marketer's side this must read as an actual, fresh generation
    run, not a reveal of something that already existed: a short, multi-step
    st.status walks through the same shape of work a real run does
    (copy/visual direction, then the concepts, then finalizing), summing to
    DEMO_REVEAL_DELAY_SECONDS, for the WHOLE batch at once (three concepts
    are meant to appear together, the way they did in the real run). Only
    then does it reveal the exact creative recorded in the demo playback
    manifest for each concept. A concept missing from the manifest, or whose
    recorded asset no longer matches, is marked "unavailable" internally (no
    provider was ever called, so nothing actually "failed"), but is shown to
    the marketer with the SAME wording as a live failure (see _render_concept):
    the cache is an implementation detail, never a visible product state.
    """
    n = len(work)
    step = DEMO_REVEAL_DELAY_SECONDS / 3
    with st.status("Creating creatives...", expanded=True) as status:
        st.write("Preparing copy and visual direction")
        time.sleep(step)
        st.write(f"Creating {n} ad concept{'s' if n != 1 else ''}")
        time.sleep(step)
        st.write("Finalizing creative set")
        time.sleep(step)
        for _, concept in work:
            slot = slots[concept.concept_id]
            try:
                creative = demo_playback.resolve_playback_creative(client_id, concept.concept_id, slot["fingerprint"])
                slot.update(status="ready", creative=creative, versions=[creative], error=None, force=False, spec=None)
            except demo_playback.DemoPlaybackUnavailable as exc:
                _fail(slot, str(exc), status="unavailable")
        status.update(label="Creatives ready", state="complete", expanded=False)


def _process_pending(client_id: str, plan: CreativePlan) -> None:
    """Runs every pending generation/reveal, once, AFTER the page has
    rendered (so pending cards show "Generating"). Ends with one
    st.rerun() so the finished cards render; because each slot's status is
    flipped synchronously before that rerun, no rerun can find a stale
    pending slot to process again. Branches on CREATIVE_GENERATION_MODE at
    this ONE seam: live mode calls the real pipeline, demo mode calls only
    demo_playback (never a provider). Neither branch runs, and no delay
    ever happens, unless at least one concept was just explicitly marked
    pending by a click.
    """
    slots = _slots()
    work = [(f, c) for f in plan.families for c in f.concepts if slots.get(c.concept_id, {}).get("status") == "pending"]
    if not work:
        return
    if creative_generation_mode() == CREATIVE_GENERATION_MODE_LIVE:
        _process_pending_live(client_id, plan, work, slots)
    else:
        _process_pending_demo(client_id, work, slots)
    st.rerun()


def _short_constant_phrase(constants_to_preserve: list[str]) -> str:
    return " · ".join(item.split(":", 1)[1].strip() for item in constants_to_preserve)


def _render_family(client_id: str, index: int, family: CreativeFamily) -> None:
    """Presentation order (Milestone 26), so the opportunity reads as a
    story: why it is in the plan -> who we are speaking to -> the question
    the creatives are designed to answer (the single most emphasized line)
    -> what we are changing and holding consistent -> the concepts. Every
    value is the Creative Opportunity's own structured field, unchanged;
    only labels ("Changing", "Keeping consistent") and hierarchy are new.
    """
    opportunity = family.opportunity
    pain_point = ui.theme_label(opportunity.pain_point)
    ui.section_header(f"Creative Opportunity {index:02d} · {pain_point}")

    with ui.card("primary", rhythm=True):
        ui.badge_row([f"{opportunity.product} · {opportunity.funnel_stage}"])

        ui.grouped_field_grid(
            [
                ("Why this is in the plan", [("", opportunity.why_in_plan)]),
                (
                    "Strategy",
                    [
                        ("Avatar", opportunity.avatar),
                        ("Awareness stage", opportunity.awareness_stage),
                        ("Pain point", pain_point),
                    ],
                ),
            ]
        )

        ui.callout("What we want to learn", opportunity.what_we_want_to_learn, emphasis=True)

        ui.grouped_field_grid(
            [
                (
                    "Test design",
                    [
                        ("Changing", opportunity.variable_to_test),
                        ("Keeping consistent", _short_constant_phrase(opportunity.constants_to_preserve)),
                    ],
                ),
            ]
        )

        with st.expander("View evidence"):
            st.caption(f"{opportunity.confidence.capitalize()} confidence")
            _render_evidence(opportunity.evidence)

    # Milestone 28.4: "Generate creatives" now sits BELOW the three concept
    # cards, not above them, so the section reads in order - review the
    # three directions, then ask Creative Studio to build them - rather than
    # presenting the action before there is anything to react to.
    ui.section_header("Creative concepts", "Three directions derived from the strategy above.", level="subsection")
    concept_cols = st.columns(len(family.concepts))
    for col, concept in zip(concept_cols, family.concepts):
        with col:
            _render_concept(client_id, family, concept)
    _render_generation_controls(client_id, family)
    _render_generation_details(family)


def _learning_question(opportunity) -> str:
    """Delegates to the single shared definition
    (agents.creative_studio.execution.learning_question_for), so the copy
    step, the generated ad's spec, and this handoff can never disagree."""
    return learning_question_for(opportunity)


def _arm_from_creative(concept, creative) -> dict:
    """ONE experiment arm carried over EXACTLY as created in Creative Lab:
    the generated asset's id and path, and its copy verbatim from the
    creative's own AdExecutionSpec (never re-derived, re-worded or
    substituted from the concept's placeholder text). Experiments renders
    and tests exactly this; it never regenerates anything.

    Old keys (on_image_*, visual_direction, angle, why_this_concept_exists)
    are kept so the simulation and Performance Agent read the same fields
    they always did.
    """
    spec = creative.ad_spec
    return {
        "generated_id": creative.generated_id,
        "concept_id": concept.concept_id,
        "concept_name": spec.concept_name,
        "image_path": str(creative.image_path),
        "metadata_path": str(creative.metadata_path),
        "version": creative.version,
        "visual_direction": spec.visual_direction,
        "angle": spec.messaging_angle,
        "why_this_concept_exists": spec.why_this_concept_exists,
        "on_image_headline": spec.on_image_headline,
        "primary_text": spec.primary_text,
        "meta_headline": spec.meta_headline,
        "description": spec.description,
        "cta": spec.cta,
        "on_image_supporting_copy": "",
        "on_image_proof": "",
        "on_image_cta": spec.cta,
        "provider": creative.provider,
        "model": creative.model,
        "generated_at": creative.generated_at,
        "data_type": creative.data_type,
        "ad_spec": spec.to_dict(),
    }


def _build_family_handoff(client_id: str, family: CreativeFamily, selected: list) -> dict:
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

    representative = selected[0][1].ad_spec
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
            "headline": representative.meta_headline,
            "description": representative.description,
            "cta": representative.cta,
            "selected_creative_versions": [_arm_from_creative(concept, creative) for concept, creative in selected],
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
        selected = _selected_creatives(family)
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
        _render_family(client_id, index, family)
        st.divider()

    ui.section_header("Prepare experiments", "Choose which finished ads to test for each opportunity, then prepare an experiment.")
    any_selected = any(_selected_creatives(family) for family in plan.families)
    if st.button("Prepare selected experiments", type="primary", disabled=not any_selected):
        n_prepared = _prepare_selected_experiments(client_id, plan)
        if n_prepared:
            st.switch_page("app_pages/experiments.py")
    if not any_selected:
        st.caption("Generate creatives, then include at least one finished ad in at least one opportunity to prepare an experiment.")

if creative_generation_mode() != CREATIVE_GENERATION_MODE_LIVE:
    st.divider()
    with st.expander("Demo controls"):
        st.button(
            "Reset demo", key="clab_reset_demo", on_click=_reset_demo_reveal_state,
            help="Returns every opportunity to its pre-generation state for this session. Does not delete any "
            "generated asset, metadata, or prepared experiment.",
        )

_process_pending(client_id, plan)
