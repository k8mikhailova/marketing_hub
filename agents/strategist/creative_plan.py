"""Creative Plan: the Strategist's synthesis of ALL current findings into a
set of Creative Families worth developing, plus cross-cutting context.

Milestone 22 (Creative Lab V2) replaces the old model, where a marketer
picked ONE Marketing Intelligence finding and Creative Lab built one ad
package and one experiment from it. Here, every current finding is
considered together: an experiment-worthy finding (Emerging Opportunity or
Messaging Gap) becomes its own CreativeFamily (a CreativeOpportunity plus 3
angle-differentiated CreativeConcepts, see agents/strategist/engine.py and
agents/creative_studio/engine.py); a Performance Pattern finding is never
promoted to its own family (it describes an already-observed pattern in one
specific product/funnel-stage context, not a new opportunity), and instead
becomes cross_cutting_context: a short, explicitly-scoped note the
Strategist attaches to the whole plan, informing tone without being
misrepresented as evidence for a different product or funnel stage.

This module only orchestrates: it calls agents.strategist.engine for
opportunity-level strategy and agents.creative_studio.engine for
concept-level copy, and adds nothing here that either of those modules
should own. Exactly like every other agent module in this project, this is
the deterministic "preview" implementation (generated_by=GENERATED_BY_PREVIEW
throughout); a future live Strategist call would return the same
CreativePlan shape.

Architecture note for future work: build_creative_plan takes no argument
besides client_id today, but nothing here assumes findings are the ONLY
possible input. A future approved-learning store (not built in this
milestone; see README) could be read here alongside generate_findings and
folded into why_in_plan/strategist_summary without changing this module's
public shape, which is why evidence_strip already carries a
(currently-always-zero) saved_learnings count rather than omitting the
concept entirely.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agents.creative_studio.engine import CreativeConcept, generate_concepts_for_opportunity
from agents.intelligence.engine import GENERATED_BY_PREVIEW, Finding, generate_findings
from agents.strategist.engine import CreativeOpportunity, build_creative_opportunity
from core.data import load_creative_catalog, load_customer_signals, load_performance_with_creatives


@dataclass
class CreativeFamily:
    """One CreativeOpportunity plus the concepts built to explore it. A
    family is the unit a marketer reviews and includes/excludes concepts
    from; it is also, by default, the unit "Prepare Experiments" turns into
    one proposed experiment (never mixed with another family's concepts).
    """

    opportunity: CreativeOpportunity
    concepts: list[CreativeConcept] = field(default_factory=list)


@dataclass
class CreativePlan:
    """The Strategist's full synthesis for one client, at the moment it was
    built: every current creative family, the cross-cutting Performance
    Pattern context (if any), a short human-readable synthesis paragraph,
    and the real evidence counts shown in the plan's own evidence strip.
    Built fresh on every Creative Lab page load (cheap, deterministic,
    side-effect-free, like every other agent "preview" call in this
    project); nothing here is cached or persisted.
    """

    plan_id: str
    client_id: str
    generated_at: str
    strategist_summary: str
    families: list[CreativeFamily] = field(default_factory=list)
    cross_cutting_finding: Finding | None = None
    cross_cutting_context: str | None = None
    evidence_strip: dict = field(default_factory=dict)
    generated_by: str = GENERATED_BY_PREVIEW
    # Milestone 31: the same content as strategist_summary/cross_cutting_context,
    # split into (headline, aside) so app_pages/creative_lab.py can show it as
    # two scannable labeled blocks (ui.insight_blocks) instead of one dense
    # paragraph. The joined single-string fields above are unchanged in type -
    # cross_cutting_context specifically is also read as live-generation
    # performance_context input (agents/creative_studio/pipeline.py, via
    # app_pages/creative_lab.py), so it can't become a tuple itself.
    strategist_summary_parts: tuple[str, str] = ("", "")
    cross_cutting_context_parts: tuple[str, str] | None = None


def cross_cutting_context_parts(finding: Finding) -> tuple[str, str]:
    """The Strategist's own framing of a Performance Pattern finding as
    plan-wide CONTEXT, never as a third family, as (what we're seeing, how
    we're using it). Milestone 31: previously one paragraph that stated the
    same statistic twice (the finding's own summary, then its why_it_matters,
    which already restates the comparison before adding the volume/trust
    detail) before finally explaining the travel rule; the full evidence and
    volume numbers are already one click away via the finding on Insights,
    so this note's own job is just to say what the pattern is and how far it
    travels, once each, never to re-prove it's credible. Never adds a new
    number or claim of its own.
    """
    what_we_see = finding.summary
    how_we_use_it = (
        "It's a tone cue for wherever a concept's own angle calls for it, not proof it wins in a different "
        "product or funnel stage, and it never substitutes for a creative opportunity's own evidence."
    )
    return what_we_see, how_we_use_it


def cross_cutting_context_note(finding: Finding) -> str:
    """The single-string form of cross_cutting_context_parts, unchanged in
    type since it also doubles as live creative generation's
    performance_context input (see CreativePlan's own docstring above).
    """
    what_we_see, how_we_use_it = cross_cutting_context_parts(finding)
    return f"{what_we_see} {how_we_use_it}"


def _strategist_summary_parts(families: list[CreativeFamily], cross_cutting: Finding | None) -> tuple[str, str]:
    """(the plan itself, an optional aside about cross-cutting context), so
    app_pages/creative_lab.py can show them as two scannable labeled blocks
    instead of one paragraph that used to run the actual plan straight into
    an unrelated tone-context aside. _strategist_summary (below) still
    returns the joined single-string form, unchanged in type.
    """
    if not families:
        return "No creative opportunities clear the evidence bar for the current data.", ""

    territories = "; ".join(
        f'"{family.opportunity.pain_point}" for {family.opportunity.product}' for family in families
    )
    n = len(families)
    plan_line = (
        f"{n} creative opportunit{'y' if n == 1 else 'ies'} worth developing next: {territories}. "
        "In each case, it's something customers keep bringing up that our creative isn't addressing yet."
    )
    aside = ""
    if cross_cutting:
        detail = cross_cutting.summary[0].lower() + cross_cutting.summary[1:]
        aside = (
            f"One more thing worth keeping in mind as we build these: {detail} That's supporting context for "
            "tone, not a reason to add another opportunity."
        )
    return plan_line, aside


def _strategist_summary(families: list[CreativeFamily], cross_cutting: Finding | None) -> str:
    plan_line, aside = _strategist_summary_parts(families, cross_cutting)
    return f"{plan_line} {aside}".strip() if aside else plan_line


def _evidence_strip(client_id: str) -> dict:
    """Real, dynamically-computed counts for the plan's own evidence strip,
    never hardcoded: customer signal volume and creative catalog size come
    straight from core.data; the performance window is the actual span of
    dates present in meta_ads.csv (via the same joined frame every
    performance calculation in this project already uses), not an assumed
    fixed number of days. saved_learnings is always 0 today: durable Save
    Learning (approved_learnings.json) is explicit future work this
    milestone does not implement, so this is an honest current count, not a
    placeholder pretending the feature exists.
    """
    signals = load_customer_signals(client_id)
    catalog = load_creative_catalog(client_id)
    joined = load_performance_with_creatives(client_id)
    performance_days = int((joined["date"].max() - joined["date"].min()).days) + 1 if not joined.empty else 0
    return {
        "customer_signals": int(len(signals)),
        "current_creatives": int(len(catalog)),
        "performance_days": performance_days,
        "saved_learnings": 0,
    }


def build_creative_plan(client_id: str) -> CreativePlan:
    """The one entry point: run the Intelligence Agent's current findings
    through the Strategist (one CreativeOpportunity per experiment-worthy
    finding) and Creative Studio (3 angle concepts per opportunity), and
    attach the Performance Pattern finding, if any, as cross-cutting context
    rather than a family of its own. Findings that clear neither bar
    (Saturated Theme, or simply none this run) contribute nothing: this
    never pads the plan with a family or a context note the evidence
    doesn't support.
    """
    findings = generate_findings(client_id, max_findings=3)
    cross_cutting = next((f for f in findings if f.type == "Performance Pattern"), None)

    families = []
    for finding in findings:
        if finding.type == "Performance Pattern":
            continue
        opportunity = build_creative_opportunity(client_id, finding)
        concepts = generate_concepts_for_opportunity(client_id, opportunity)
        families.append(CreativeFamily(opportunity=opportunity, concepts=concepts))

    return CreativePlan(
        plan_id=f"creative_plan::{client_id}",
        client_id=client_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        strategist_summary=_strategist_summary(families, cross_cutting),
        strategist_summary_parts=_strategist_summary_parts(families, cross_cutting),
        families=families,
        cross_cutting_finding=cross_cutting,
        cross_cutting_context=cross_cutting_context_note(cross_cutting) if cross_cutting else None,
        cross_cutting_context_parts=cross_cutting_context_parts(cross_cutting) if cross_cutting else None,
        evidence_strip=_evidence_strip(client_id),
    )
