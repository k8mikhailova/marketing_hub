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


def cross_cutting_context_note(finding: Finding) -> str:
    """The Strategist's own framing of a Performance Pattern finding as
    plan-wide CONTEXT, never as a third family: recombines the finding's own
    summary/why_it_matters (which already names the exact product/funnel
    stage it was observed in, and already says explicitly that it may not
    hold elsewhere) with one plan-level sentence saying how far that context
    is allowed to travel. Never adds a new number or claim of its own.
    """
    return (
        f"{finding.summary} {finding.why_it_matters} For this plan: recognizable, natural customer language is "
        "used as a general tone cue where a concept's own angle calls for it, but this pattern is supporting "
        "context from one specific product and funnel stage, not proof that customer-language messaging wins in a "
        "different context, so it never substitutes for a family's own evidence."
    )


def _strategist_summary(families: list[CreativeFamily], cross_cutting: Finding | None) -> str:
    if not families:
        return "No creative opportunities clear the evidence bar for the current data."

    territories = "; ".join(
        f'"{family.opportunity.pain_point}" for {family.opportunity.product}' for family in families
    )
    n = len(families)
    summary = (
        f"Customer signals, current creative coverage, and campaign performance point to {n} creative "
        f"opportunit{'y' if n == 1 else 'ies'} worth developing next: {territories}."
    )
    if cross_cutting:
        detail = cross_cutting.summary[0].lower() + cross_cutting.summary[1:]
        summary += (
            f" Separately, {detail} That pattern is carried into this plan as supporting context for tone, not "
            "as a reason to add a third family."
        )
    return summary


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
        families=families,
        cross_cutting_finding=cross_cutting,
        cross_cutting_context=cross_cutting_context_note(cross_cutting) if cross_cutting else None,
        evidence_strip=_evidence_strip(client_id),
    )
