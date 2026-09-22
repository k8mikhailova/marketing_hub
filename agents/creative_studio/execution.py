"""Creative Studio V3 (Milestone 27): the AD EXECUTION SPEC, the structured
intermediate representation between a strategic Creative Concept and a
finished, generated ad.

Creative Opportunity -> Creative Concept -> AdExecutionSpec -> image request
-> finished creative.

THE COPY WE INTEND TO SHIP EXISTS AS DATA BEFORE ANY IMAGE IS GENERATED. The
image model is told, in a separate step, exactly which on-image words to
render; it is never asked to invent strategy or copy inside a visual prompt.

Responsibilities are split on purpose:

- This module (deterministic Python) owns the FACTS and the CONTRACT: which
  strategy fields feed the copy step, which fields are fixed (product, CTA,
  approved proof, constraints), what a valid spec looks like, and validation.
- A TextGenerationProvider (a thin seam; OpenAI implementation in
  text_provider.py) owns only INTERPRETATION: turning the structured strategy
  into candidate copy and a visual direction. It returns a small structured
  object (ExecutionCopy); Python fills every other field and validates the
  whole thing. Malformed or non-compliant output is never silently accepted:
  ExecutionSpecError carries the specific issues and the caller (Creative Lab)
  shows a recoverable error with a retry, without touching the Creative Plan.

Grounding rules enforced in validate_execution_spec (the same claim-safety
philosophy as agents/creative_studio/engine.py's validators, reusing its
PERFORMANCE_CLAIM_PATTERN/_numbers_in/_text_too_similar rather than a second
copy of that logic): no number that is not in the approved product proof, no
performance/result language, no certification/health/savings/guarantee/
testimonial language, no reuse of the reference ad's headline, and the CTA is
the opportunity's own constant, never model-chosen. Customer signals are
passed to the copy step as evidence of what customers TALK ABOUT (synthetic
demo data); the context says explicitly that they are not evidence that the
product solves those problems, and the constraints forbid presenting them as
testimonials.
"""
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel

from agents.creative_studio.engine import (
    PERFORMANCE_CLAIM_PATTERN,
    CreativeConcept,
    _numbers_in,
    _text_too_similar,
)
from agents.strategist.engine import CreativeOpportunity
from core.data import load_creative_catalog, load_customer_signals

GENERATED_BY_AGENT = "agent"
DATA_TYPE_AI_FROM_DEMO_CONTEXT = "ai_generated_from_demo_context"

# Ad-realistic length ceilings. On-image copy has to fit inside a creative;
# Meta's own headline/description slots are short. Deliberately named
# constants (not magic numbers in a condition), same convention as this
# project's other validators.
MAX_ON_IMAGE_HEADLINE_CHARS = 70
MAX_ON_IMAGE_HEADLINE_WORDS = 10
MAX_PRIMARY_TEXT_CHARS = 220
MAX_META_HEADLINE_CHARS = 40
MAX_DESCRIPTION_CHARS = 60
CUSTOMER_LANGUAGE_SAMPLE = 5
PROOF_REFERENCE_SAMPLE = 6

PROHIBITED_CLAIMS = [
    "Invented product capabilities or features",
    "Filtration percentages, contaminant counts or any number not present in the approved proof",
    "Certifications, standards or third-party endorsements",
    "Health outcomes or medical claims",
    "Savings, price or value claims",
    "Guarantees",
    "Customer testimonials or quotes presented as real",
    "Performance or results claims",
    "Scientific or laboratory claims",
]

# Language that is never allowed in generated ad copy, on top of the shared
# performance-claim screen. Broad by design: the goal is catching an
# obviously ungrounded claim, not perfect coverage.
_UNGROUNDED_CLAIM_PATTERN = re.compile(
    r"\bcertif(?:ied|ication|ications)\b|\bnsf\b|\bfda\b|\bepa\b|\bguarantee[sd]?\b|\bclinical(?:ly)?\b|"
    r"\bscientific(?:ally)?\b|\blab[- ]tested\b|\bcures?\b|\bheals?\b|\bdetox\w*\b|\baward[- ]winning\b|"
    r"\blifetime\b|\bsav(?:e|es|ing|ings)\b|\bcheaper\b|\bdiscount\b|\bcustomers? (?:say|love|report)\b|"
    r"\breviews? (?:say|show)\b|\b100\s*%|\bno\.? ?1\b|\btop[- ]rated\b|\bhealthier\b|\bsafe to drink\b",
    re.IGNORECASE,
)
_EM_DASH = chr(0x2014)
_EN_DASH = chr(0x2013)
_QUOTE_CHARS = re.compile(r"[\"“”]")


class ExecutionCopy(BaseModel):
    """The ONLY structure the text model is asked to return: candidate copy
    plus a visual direction. Everything else in an AdExecutionSpec (ids,
    product, CTA, proof, constraints, learning question) is filled in by
    Python from the strategy, so a model can never alter a constant.
    """

    on_image_headline: str
    primary_text: str
    meta_headline: str
    description: str
    visual_direction: str


class ExecutionSpecError(Exception):
    """A spec could not be produced or did not validate. `issues` lists the
    specific problems; the message is always safe to show a marketer (never
    an API key or raw provider internals)."""

    def __init__(self, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.issues = issues or []


class TextGenerationError(Exception):
    """A text-provider failure (missing key, auth, timeout, refusal,
    malformed response). Message is safe to show a user directly."""


class TextGenerationProvider(Protocol):
    """The one interface every text-generation provider implements: given a
    system prompt and a user prompt, return a dict matching ExecutionCopy.
    Creative Lab never talks to OpenAI directly; it only ever sees this."""

    model: str

    def generate_execution_copy(self, system: str, user: str) -> dict: ...


@dataclass
class AdExecutionSpec:
    """Everything needed to render, review, and later TEST one finished ad,
    kept as data separate from the image. Layers (Milestone 27 brief):

    strategy   : concept_id, opportunity_id, concept_name, messaging_angle,
                 strategic_intent, learning_question, customer_theme, avatar,
                 awareness_stage, product, funnel_stage
    copy       : on_image_headline (rendered inside the image), primary_text,
                 meta_headline, description, cta (all outside the image
                 except the on-image headline)
    visual     : visual_direction, required_product, proof_to_preserve,
                 reference_creative_id
    experiment : variable_changed, constants_preserved,
                 why_this_concept_exists (same text as strategic_intent,
                 kept under its experiment-facing name)
    provenance : generated_by, data_type, text_model, generated_at
    """

    client_id: str
    opportunity_id: str
    source_finding_id: str
    concept_id: str
    concept_name: str
    messaging_angle: str
    strategic_intent: str
    learning_question: str
    customer_theme: str
    avatar: str
    awareness_stage: str
    product: str
    funnel_stage: str
    on_image_headline: str
    primary_text: str
    meta_headline: str
    description: str
    cta: str
    visual_direction: str
    required_product: str
    proof_to_preserve: str
    reference_creative_id: str
    variable_changed: str
    constants_preserved: list[str] = field(default_factory=list)
    prohibited_claims: list[str] = field(default_factory=list)
    why_this_concept_exists: str = ""
    generated_by: str = GENERATED_BY_AGENT
    data_type: str = DATA_TYPE_AI_FROM_DEMO_CONTEXT
    text_model: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AdExecutionSpec":
        names = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in names})


def learning_question_for(opportunity: CreativeOpportunity) -> str:
    """The one QUESTION an opportunity's experiment exists to answer, built
    only from its structured fields (never a hardcoded per-demo sentence).
    Single definition, shared by the copy step and the experiment handoff so
    they can never disagree."""
    return f'Which way of framing "{opportunity.pain_point}" for {opportunity.product} deserves further creative investment?'


# ---------------------------------------------------------------------------
# Context (Python owns the facts)
# ---------------------------------------------------------------------------


@dataclass
class CopyContext:
    system: str
    user: str
    approved_proof: list[str]
    reference_headline: str
    cta: str
    proof_to_preserve: str


_SYSTEM_PROMPT = """You write the copy and visual direction for ONE finished paid-social ad, as one arm of a controlled creative experiment.

You are given a structured strategy. Your job is to EXECUTE the specific strategic concept you are assigned, not to invent strategy, and not to write a generic ad. The concept exists to test one hypothesis about what moves the audience; its copy must clearly express that concept's intent and be meaningfully different from the other concepts in the same experiment.

HARD RULES
- Use only claims supported by the APPROVED PROOF and the approved copy examples provided. Never invent product capabilities, filtration percentages, contaminant counts, certifications, health outcomes, savings or price claims, guarantees, testimonials, performance claims, or scientific claims.
- Do not include any number unless it appears verbatim in the approved proof.
- Customer signals show what customers TALK ABOUT. They are not evidence that the product solves those problems, and they are not testimonials: never present them as quotes, reviews, or things customers say about the product. You may reflect the customer's own everyday language and concern.
- Past ads are references for brand feel and product presentation only. Do not copy or lightly reword any past headline.
- Do not use double quotation marks anywhere in the copy. Do not use em dashes.
- Keep everything short enough to be real ad copy: on_image_headline at most 10 words (it is rendered inside the image); primary_text at most 2 short sentences; meta_headline at most 40 characters; description at most 60 characters.

OUTPUT FIELDS
- on_image_headline: the headline that will be printed on the image.
- primary_text: the Meta primary text shown above the image (do not repeat the headline).
- meta_headline: the Meta headline slot below the image.
- description: the Meta description slot (short; may be empty).
- visual_direction: one or two sentences describing the scene, composition and mood that best express THIS concept with the product. Describe visuals only, no words to print.
"""


def _customer_language(client_id: str, opportunity: CreativeOpportunity) -> list[str]:
    signals = load_customer_signals(client_id)
    theme = signals[signals["demo_theme_label"] == opportunity.pain_point]
    scoped = theme[theme["product_context"] == opportunity.product]
    if len(scoped) < 3:
        scoped = theme
    scoped = scoped.sort_values(["date", "signal_id"], ascending=[False, True])
    return [str(t) for t in scoped["text"].head(CUSTOMER_LANGUAGE_SAMPLE)]


def _approved_copy_references(client_id: str, opportunity: CreativeOpportunity) -> tuple[list[str], str, str]:
    """(approved proof/copy strings for this product, control headline,
    control primary text). The approved proof is what already runs for this
    product in the catalog; nothing else counts as approved."""
    catalog = load_creative_catalog(client_id)
    product_rows = catalog[catalog["product_name"] == opportunity.product]
    control = catalog[catalog["creative_id"] == opportunity.control_creative_id].iloc[0]
    proof = []
    for text in [control["primary_text"], *product_rows["primary_text"].tolist(), *product_rows["headline"].tolist()]:
        if text not in proof:
            proof.append(str(text))
    return proof[:PROOF_REFERENCE_SAMPLE], str(control["headline"]), str(control["primary_text"])


def build_copy_context(
    client_id: str,
    opportunity: CreativeOpportunity,
    concept: CreativeConcept,
    siblings: list[CreativeConcept],
    performance_context: str = "",
) -> CopyContext:
    """The structured input to the copy step, assembled entirely from the
    Creative Opportunity, the assigned Creative Concept, the other concepts
    in the same experiment (so the model can differentiate), synthetic
    customer signals, the catalog's approved copy, and (if any) the plan's
    cross-cutting performance context with its own scope caveat."""
    approved, reference_headline, control_primary = _approved_copy_references(client_id, opportunity)
    language = _customer_language(client_id, opportunity)
    others = [c for c in siblings if c.concept_id != concept.concept_id]

    sections = [
        "CREATIVE OPPORTUNITY\n"
        f"Customer pain point: {opportunity.pain_point}\n"
        f"Product: {opportunity.product}\n"
        f"Funnel stage: {opportunity.funnel_stage}\n"
        f"Avatar: {opportunity.avatar}\n"
        f"Awareness stage: {opportunity.awareness_stage}\n"
        f"Why this opportunity is in the plan: {opportunity.why_in_plan}",
        f"LEARNING QUESTION THIS EXPERIMENT ANSWERS\n{learning_question_for(opportunity)}\n"
        f"Variable being changed across the concepts: {opportunity.variable_to_test}",
        "YOUR ASSIGNED CONCEPT\n"
        f"Concept: {concept.concept_name}\n"
        f"Messaging angle: {concept.angle}\n"
        f"Why this concept exists: {concept.why_this_concept_exists}",
        "THE OTHER CONCEPTS IN THIS EXPERIMENT (yours must be clearly different from these)\n"
        + ("\n".join(f"- {c.concept_name}: {c.angle}" for c in others) or "- none"),
        "APPROVED PRODUCT PROOF AND APPROVED COPY YOU MAY DRAW ON (the only claims you may make)\n"
        f"Core proof to preserve: {concept.reason_to_believe or control_primary}\n"
        + "\n".join(f"- {t}" for t in approved),
        "CUSTOMER LANGUAGE (synthetic demo signals: evidence of what customers talk about, NOT proof the product solves it, NOT testimonials)\n"
        + ("\n".join(f"- {t}" for t in language) or "- none available"),
        "REFERENCE AD (brand feel only; do not copy or reword)\n"
        f"Existing headline: {reference_headline}",
    ]
    if performance_context:
        sections.append(
            "PERFORMANCE CONTEXT (supporting context from one specific product and funnel stage; not proof for "
            f"this product or stage)\n{performance_context}"
        )
    sections.append(
        "FIXED FOR EVERY CONCEPT (do not change)\n"
        f"CTA: {concept.cta}\nFormat: {concept.format}\n"
        + "\n".join(f"- {c}" for c in concept.constants_to_preserve)
    )
    return CopyContext(
        system=_SYSTEM_PROMPT,
        user="\n\n".join(sections),
        approved_proof=approved,
        reference_headline=reference_headline,
        cta=concept.cta,
        proof_to_preserve=concept.reason_to_believe or control_primary,
    )


# ---------------------------------------------------------------------------
# Validation (Python decides what is acceptable)
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Deterministic clean-up of model output that must never appear in
    shipped copy (em/en dashes, stray whitespace). The only mutation applied
    before validation."""
    return re.sub(r"\s+", " ", text.replace(_EM_DASH, " - ").replace(_EN_DASH, " - ")).strip()


def validate_execution_spec(spec: AdExecutionSpec, approved_proof: list[str], reference_headline: str) -> list[str]:
    """Issues (empty list if valid). Checks structure, length, grounding, and
    that fixed fields were not altered."""
    issues: list[str] = []
    for name in ("on_image_headline", "primary_text", "meta_headline", "visual_direction"):
        if not getattr(spec, name).strip():
            issues.append(f"{name} is empty.")
    if len(spec.on_image_headline) > MAX_ON_IMAGE_HEADLINE_CHARS or len(spec.on_image_headline.split()) > MAX_ON_IMAGE_HEADLINE_WORDS:
        issues.append("on_image_headline is too long to work as on-image copy.")
    if len(spec.primary_text) > MAX_PRIMARY_TEXT_CHARS:
        issues.append("primary_text is too long.")
    if len(spec.meta_headline) > MAX_META_HEADLINE_CHARS:
        issues.append("meta_headline is too long for the Meta headline slot.")
    if len(spec.description) > MAX_DESCRIPTION_CHARS:
        issues.append("description is too long for the Meta description slot.")

    copy_text = " ".join([spec.on_image_headline, spec.primary_text, spec.meta_headline, spec.description])
    allowed_numbers = _numbers_in(" ".join(approved_proof + [spec.proof_to_preserve]))
    invented = _numbers_in(copy_text) - allowed_numbers
    if invented:
        issues.append(f"copy introduces numbers not present in the approved proof: {sorted(invented)}.")
    if PERFORMANCE_CLAIM_PATTERN.search(copy_text):
        issues.append("copy contains an unsupported performance claim.")
    if _UNGROUNDED_CLAIM_PATTERN.search(copy_text):
        issues.append("copy contains an ungrounded claim (certification, health, savings, guarantee, testimonial or scientific language).")
    if _QUOTE_CHARS.search(copy_text):
        issues.append("copy contains quotation marks, which could read as a customer quote.")
    if _EM_DASH in copy_text:
        issues.append("copy contains an em dash.")
    if spec.on_image_headline.strip().lower() == reference_headline.strip().lower():
        issues.append("on_image_headline reuses the reference ad's headline.")
    if not spec.cta.strip():
        issues.append("cta is empty.")
    return issues


def validate_distinct_specs(specs: list[AdExecutionSpec]) -> list[str]:
    """Concepts in one experiment must be strategically distinct: different
    concept ids/angles, and copy that is not a near-duplicate of another
    concept's. Returns issue strings."""
    issues: list[str] = []
    for i in range(len(specs)):
        for j in range(i + 1, len(specs)):
            a, b = specs[i], specs[j]
            if a.concept_id == b.concept_id or a.messaging_angle == b.messaging_angle:
                issues.append(f"{a.concept_name} and {b.concept_name} do not express distinct strategic concepts.")
            if _text_too_similar(f"{a.on_image_headline} {a.primary_text}", f"{b.on_image_headline} {b.primary_text}"):
                issues.append(f"{a.concept_name} and {b.concept_name} copy is too similar.")
    return issues


def generate_execution_spec(
    client_id: str,
    opportunity: CreativeOpportunity,
    concept: CreativeConcept,
    siblings: list[CreativeConcept],
    provider: TextGenerationProvider,
    performance_context: str = "",
    accepted_specs: list[AdExecutionSpec] | None = None,
) -> AdExecutionSpec:
    """Produce ONE validated AdExecutionSpec for a concept: build the
    context, make exactly one provider call, parse and validate the result.

    Raises ExecutionSpecError (with issues) for malformed or non-compliant
    output, TextGenerationError for a provider failure. Exactly one text call
    per invocation: retries are a deliberate caller decision, never hidden
    here, because every call costs money.
    """
    context = build_copy_context(client_id, opportunity, concept, siblings, performance_context)
    raw = provider.generate_execution_copy(context.system, context.user)
    try:
        candidate = ExecutionCopy.model_validate(raw)
    except Exception:
        raise ExecutionSpecError("The copy generator returned a malformed result. Try again.", ["malformed structured output"])

    spec = AdExecutionSpec(
        client_id=client_id,
        opportunity_id=opportunity.opportunity_id,
        source_finding_id=opportunity.source_finding_id,
        concept_id=concept.concept_id,
        concept_name=concept.concept_name,
        messaging_angle=concept.angle,
        strategic_intent=concept.why_this_concept_exists,
        learning_question=learning_question_for(opportunity),
        customer_theme=opportunity.pain_point,
        avatar=opportunity.avatar,
        awareness_stage=opportunity.awareness_stage,
        product=opportunity.product,
        funnel_stage=opportunity.funnel_stage,
        on_image_headline=_normalize(candidate.on_image_headline),
        primary_text=_normalize(candidate.primary_text),
        meta_headline=_normalize(candidate.meta_headline),
        description=_normalize(candidate.description),
        cta=context.cta,
        visual_direction=_normalize(candidate.visual_direction),
        required_product=opportunity.product,
        proof_to_preserve=context.proof_to_preserve,
        reference_creative_id=opportunity.control_creative_id,
        variable_changed=opportunity.variable_to_test,
        constants_preserved=list(opportunity.constants_to_preserve),
        prohibited_claims=list(PROHIBITED_CLAIMS),
        why_this_concept_exists=concept.why_this_concept_exists,
        generated_by=GENERATED_BY_AGENT,
        text_model=getattr(provider, "model", ""),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    issues = validate_execution_spec(spec, context.approved_proof, context.reference_headline)
    if accepted_specs:
        issues += validate_distinct_specs([*accepted_specs, spec])
    if issues:
        raise ExecutionSpecError("The generated copy did not pass validation: " + " ".join(issues), issues)
    return spec


__all__ = [
    "AdExecutionSpec", "CopyContext", "ExecutionCopy", "ExecutionSpecError", "TextGenerationError",
    "TextGenerationProvider", "build_copy_context", "generate_execution_spec", "learning_question_for",
    "validate_distinct_specs", "validate_execution_spec",
]
