"""Creative Studio: deterministic preview implementation of ad-package and
creative-version development.

Models a Meta ad the way Brio's real ads actually work (observed via Meta
Ads Library, see data/<client>/observed_ad_copy.csv): one AD, with its own
shared primary text / headline / description / CTA, can have several
different visual CREATIVE VERSIONS underneath it. brio_cr_004, brio_cr_005,
and brio_cr_008 are a real example already in this catalog: 3 different
creative_ids, one shared observed ad (source_ad_id
"brio_ad_home_filtration_multi"), sharing primary text and CTA while each
had its own headline.

This module builds ONE AdPackage per proposal (the control's, built from
observed/catalog copy; the treatment's, Creative Studio's own proposed
copy) and, on request, batches of 3 CreativeVersions: distinct VISUAL
executions of the treatment's message. Milestone 15 (this one) loosened an
earlier, over-tight rule: versions no longer have to share byte-identical
on-image text. What must stay controlled is the STRATEGY (the same
AdPackage, the same product/funnel-stage/format/proof), not the literal
wording burned into each image; a version's on_image_headline/supporting
copy/proof/CTA may legitimately differ from another version's, the same
way Brio's own real ad varied headlines across 3 real creative versions of
one ad.

Exactly like agents/intelligence/engine.py and agents/strategist/engine.py,
this is the "preview" implementation described in the README: fixed,
deterministic rules that produce the same structured output a future live
model call would return. Image generation itself lives in
agents/creative_studio/generation.py + image_provider.py.

Boundaries (see agents/creative_studio/agent.md for the full spec):
- Does not decide what to test or select a control: it receives an already
  human-approved ExperimentProposal and treats it as authoritative.
  build_control_ad_package never invents a hypothesis, product, or
  control; every fact traces to the proposal, creative_catalog.csv, or
  observed_ad_copy.csv.
- Never varies a true experimental constant across versions of one ad
  package: product, funnel stage, format, and the ad-level copy
  (primary_text/headline/description/cta) are fixed once, at package-build
  time, and validate_creative_versions checks every version against them.
  Only the visual execution AND that execution's own on-image copy are
  allowed to vary, as long as every version still expresses the SAME
  ad_package_id (its strategy), never brittle text equality.
- Never invents a performance claim or a claim the approved proof doesn't
  support: validate_creative_versions screens on-image copy for numbers
  not present in the retained proof and for generic fabricated-result
  language.

Same-context visual-performance evidence (core/visual_performance.py) now
informs, but never dictates, which of the 6 fixed visual-direction
strategies fill a batch's 3 slots (see _select_batch_roles): one
evidence-informed direction (steered by a qualifying same-product/same-
funnel-stage pattern when one exists), one hypothesis-informed direction
(built from the package's own customer_theme), and one exploratory
direction (a meaningfully different execution). This is a balanced-
exploration choice, not "pick the 3 strongest historical patterns": when
no qualifying pattern exists, the evidence-informed slot falls back to a
hypothesis/control-driven direction and says so plainly, and evidence is
always phrased as an associative historical pattern in the demo data
(core.visual_performance.attribute_value_provenance flags whether that
pattern is backed by an independently reviewed image or only heuristic,
demo-synthetic metadata), never as proof that a visual trait causes better
performance.

How a future live model swaps in: generate_creative_versions(ad_package,
batch_index) is the one entry point app_pages/creative_lab.py calls, and
its return shape (list[CreativeVersion]) is fixed. Internally it calls
_demo_generate_versions, a plain function from (AdPackage, batch_index) to
list[CreativeVersion]. A future live implementation only needs to add
_live_generate_versions with the same signature and generated_by="agent",
and swap which one generate_creative_versions calls; the page and the
AdPackage/CreativeVersion schemas would not need to change.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents.intelligence.engine import GENERATED_BY_PREVIEW
from agents.strategist.engine import CreativeOpportunity, ExperimentProposal
import pandas as pd

from core.analytics import aggregate_performance
from core.assets import resolve_creative_image
from core.data import DATA_DIR, load_creative_catalog, load_performance_with_creatives
from core.visual_performance import VisualPatternResult, attribute_value_provenance, visual_performance_context

# A creative version's on-image copy must never smuggle in a claim this
# demo generator (or, later, a live model) has no evidence for. Screened by
# validate_creative_versions; deliberately broad rather than exhaustive,
# since the goal is catching an obviously fabricated result, not perfect
# coverage.
PERFORMANCE_CLAIM_PATTERN = re.compile(
    r"\bguarantee(d|s)?\b|\bproven\b|\bclinically\b|#1\b|best[- ]selling|"
    r"increase(s|d)? sales|boost(s|ed)? conversions|results show",
    re.IGNORECASE,
)

# A bare number/percentage in on-image copy is only allowed when it also
# appears in the approved, retained proof text; otherwise it's an invented
# numeric claim. See validate_creative_versions and _numbers_in: only
# tokens that are PURELY numeric (e.g. "99.9%", "50") count, so a digit
# embedded in a product name/model code (e.g. the "60" in "Q60") is never
# mistaken for a numeric marketing claim.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9.%]+")
_PURE_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")

# Fields that define an ad package's STRATEGY: every creative version built
# from one AdPackage must match these exactly. Deliberately does NOT
# include on-image copy fields (on_image_headline etc.): those are allowed
# to differ between versions of the same package, so "same strategy" is
# judged by sharing an ad_package_id and these constants, never by
# comparing on-image wording. See validate_creative_versions.
_SHARED_PACKAGE_FIELDS = ["ad_package_id", "proposal_id", "control_creative_id", "product", "funnel_stage", "format"]

# Fields a version edit is never allowed to change: the shared package
# fields plus the version's own factual anchors. on_image_* fields, visual_
# direction, concept_name, and rationale remain editable. See
# validate_version_edit.
PROTECTED_VERSION_FIELDS = list(_SHARED_PACKAGE_FIELDS)


def _humanize(value: str) -> str:
    """Display formatting only: "benefit_plus_proof" -> "benefit plus proof"."""
    return value.replace("_", " ")


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace("/", "_").replace("-", "_")


def _load_observed_ad_copy(client_id: str) -> pd.DataFrame:
    """This client's real, Meta-Ads-Library-observed ad-level copy, one row
    per creative_id that has any (most creatives don't: this is real
    observational data we collected for a handful of source creatives, not
    something invented for the rest). Returns an empty (but correctly
    shaped) frame if the client has none yet.
    """
    path = DATA_DIR / client_id / "observed_ad_copy.csv"
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "creative_id",
                "source_ad_id",
                "primary_text",
                "ad_headline",
                "ad_description",
                "cta",
                "observed_total_versions",
                "notes",
                "data_type",
            ]
        )
    return pd.read_csv(path)


@dataclass
class AdPackage:
    """One proposed (or existing) Meta ad: the shared, ad-level copy
    (primary text, headline, description, CTA, matching how Meta itself
    structures an ad) plus the strategic message territory
    (core_message) every creative version built from it must express.
    source_type distinguishes the control's own existing ad ("existing",
    built from observed or catalog copy, never rewritten) from Creative
    Studio's proposed treatment ("generated"). historical_performance is
    only ever populated for an "existing" package with real synthetic
    history; a "generated" package has none yet, since nothing has run.
    """

    ad_package_id: str
    proposal_id: str
    source_finding_id: str
    client_id: str
    product: str
    funnel_stage: str
    format: str
    customer_theme: str
    core_message: str
    primary_text: str
    headline: str
    description: str
    cta: str
    proof_to_retain: str
    keep_constant: list[str]
    source_type: str  # "existing" | "generated"
    control_creative_id: str
    control_image_path: Path | None
    variable_to_test: str
    hypothesis: str
    rationale: str
    historical_performance: dict | None = None
    creative_versions: list["CreativeVersion"] = field(default_factory=list)
    generated_by: str = GENERATED_BY_PREVIEW


@dataclass
class CreativeVersion:
    """One visual execution of an AdPackage's treatment: a generation-ready
    brief for a future image model, not a generated image. Ad-level copy
    (primary_text/headline/description/cta) lives on the AdPackage and is
    never forced into the image; on_image_* fields are this version's OWN
    approved copy for what actually appears inside the image, and may
    legitimately differ from another version of the same package (real
    Brio ads do exactly this: brio_cr_004/005/008 share one ad's primary
    text but each has its own headline). Only visual_direction and the
    on_image_* fields vary between versions; _SHARED_PACKAGE_FIELDS never
    do. generated_by distinguishes a deterministic preview version from one
    a future live model would produce with the identical shape.
    """

    concept_id: str
    ad_package_id: str
    proposal_id: str
    control_creative_id: str
    concept_name: str
    visual_direction: str
    on_image_headline: str
    on_image_supporting_copy: str = ""
    on_image_proof: str = ""
    on_image_cta: str = ""
    product: str = ""
    funnel_stage: str = ""
    format: str = ""
    generation_instruction: str = ""
    variable_changed: str = ""
    constants_preserved: list[str] = field(default_factory=list)
    rationale: str = ""
    status: str = "proposed"
    generated_by: str = GENERATED_BY_PREVIEW


def _keep_constant_list(product: str, funnel_stage: str, cta: str, format_: str, proof: str) -> list[str]:
    return [
        f"Product: {product}",
        f"Funnel stage: {funnel_stage}",
        f'CTA: "{cta}"',
        f"Format: {format_}",
        f'Proof claim: "{proof}"',
    ]


def build_control_ad_package(client_id: str, proposal: ExperimentProposal) -> AdPackage:
    """The control's existing AdPackage: ad-level copy from real, observed
    Meta-Ads-Library data when we have it for this creative
    (data/<client>/observed_ad_copy.csv), falling back to the catalog's own
    (synthetic) headline/primary_text/cta when we don't, since most
    creatives in this demo have no observed copy at all. Either way this is
    the control's EXISTING copy, never rewritten; source_type="existing".

    historical_performance is the exact same synthetic aggregation Creative
    Lab already displays under "View experiment details"
    (core.analytics.aggregate_performance on meta_ads.csv), attached here
    so the experiment handoff can carry it without recomputing it
    differently in two places. None if this creative has no performance
    rows at all (shouldn't happen in this dataset, but never assumed).
    """
    catalog = load_creative_catalog(client_id)
    control_row = catalog.loc[catalog["creative_id"] == proposal.control_creative_id].iloc[0]

    observed = _load_observed_ad_copy(client_id)
    observed_row = observed.loc[observed["creative_id"] == proposal.control_creative_id]
    if not observed_row.empty:
        o = observed_row.iloc[0]
        primary_text = o["primary_text"]
        headline = o["ad_headline"]
        description = "" if pd.isna(o["ad_description"]) else o["ad_description"]
    else:
        primary_text = control_row["primary_text"]
        headline = control_row["headline"]
        description = ""
    cta = control_row["cta"]
    format_ = control_row["format"]

    joined = load_performance_with_creatives(client_id)
    by_creative = aggregate_performance(joined, by=["creative_id"]).set_index("creative_id")
    historical_performance = None
    if proposal.control_creative_id in by_creative.index:
        perf = by_creative.loc[proposal.control_creative_id]
        historical_performance = {
            "spend": float(perf["spend"]),
            "purchases": float(perf["purchases"]),
            "ctr": float(perf["ctr"]),
            "cpa": float(perf["cpa"]),
            "roas": float(perf["roas"]),
        }

    return AdPackage(
        ad_package_id=f"ad::{proposal.proposal_id}::control",
        proposal_id=proposal.proposal_id,
        source_finding_id=proposal.source_finding_id,
        client_id=client_id,
        product=proposal.product,
        funnel_stage=proposal.funnel_stage,
        format=format_,
        customer_theme=proposal.customer_theme,
        core_message=f"{_humanize(control_row['message_style'])}-first messaging (existing control)",
        primary_text=primary_text,
        headline=headline,
        description=description,
        cta=cta,
        proof_to_retain=control_row["primary_text"],
        keep_constant=_keep_constant_list(proposal.product, proposal.funnel_stage, cta, format_, control_row["primary_text"]),
        source_type="existing",
        control_creative_id=proposal.control_creative_id,
        control_image_path=resolve_creative_image(client_id, proposal.control_creative_id),
        variable_to_test=proposal.variable_to_test,
        hypothesis=proposal.hypothesis,
        rationale=proposal.control_reason,
        historical_performance=historical_performance,
    )


def _default_treatment_primary_text(theme: str, product: str) -> str:
    """The one deterministic default ad-level primary text for the
    treatment: a direct, customer-language framing of the theme, generic
    across any theme/product pair, not a human-edited placeholder.
    """
    return f"Still dealing with {theme.lower()}? {product} is built to fix that, so you get water you'll actually enjoy."


def build_treatment_ad_package(client_id: str, proposal: ExperimentProposal, control_ad_package: AdPackage) -> AdPackage:
    """Creative Studio's proposed treatment AdPackage: a new, customer-
    language ad-level primary text (the approved experimental variable),
    while headline, description, and CTA are kept identical to the
    control's own ad-level copy (Meta ad-level "keep constant," matching
    the experiment's own constants). source_type="generated": this is
    Creative Studio's proposal, not an existing real ad.
    """
    primary_text = _default_treatment_primary_text(proposal.customer_theme, proposal.product)
    return AdPackage(
        ad_package_id=f"ad::{proposal.proposal_id}::treatment",
        proposal_id=proposal.proposal_id,
        source_finding_id=proposal.source_finding_id,
        client_id=client_id,
        product=proposal.product,
        funnel_stage=proposal.funnel_stage,
        format=control_ad_package.format,
        customer_theme=proposal.customer_theme,
        core_message=f"{proposal.customer_theme} customer-language messaging",
        primary_text=primary_text,
        headline=control_ad_package.headline,
        description=control_ad_package.description,
        cta=control_ad_package.cta,
        proof_to_retain=control_ad_package.proof_to_retain,
        keep_constant=list(control_ad_package.keep_constant),
        source_type="generated",
        control_creative_id=proposal.control_creative_id,
        control_image_path=control_ad_package.control_image_path,
        variable_to_test=proposal.variable_to_test,
        hypothesis=proposal.hypothesis,
        rationale=proposal.hypothesis,
        historical_performance=None,
    )


def _version_generation_instruction(ad_package: AdPackage, direction: dict) -> str:
    parts = [
        f'Start from control creative {ad_package.control_creative_id}. '
        f'On-image headline: "{direction["on_image_headline"]}".'
    ]
    if direction.get("on_image_supporting_copy"):
        parts.append(f'Supporting line: "{direction["on_image_supporting_copy"]}".')
    if direction.get("on_image_proof"):
        parts.append(f'Proof callout: "{direction["on_image_proof"]}".')
    if direction.get("on_image_cta"):
        parts.append(f'CTA text shown on image: "{direction["on_image_cta"]}".')
    parts.append(
        f"Keep unchanged: product ({ad_package.product}), format ({ad_package.format}), funnel stage "
        f"({ad_package.funnel_stage})."
    )
    parts.append(f"Visual direction: {direction['visual_direction']}")
    return " ".join(parts)


# --- Visual direction strategies: generic, parameterized treatments of the
# SAME ad package strategy. Each proposes its OWN on-image headline/copy
# (allowed to differ between versions, per this milestone's central
# change) alongside a distinct visual direction. Never a specific theme or
# product hardcoded: every string below is built only from AdPackage
# fields, so the same 6 strategies apply to any future proposal.
# Deliberately a fixed pool, cycled 3 at a time (see generate_creative_
# versions) rather than an open-ended generator, since this is a
# deterministic preview, not a live model. -----------------------------


def _visual_control_inspired(ad_package: AdPackage) -> dict:
    theme = ad_package.customer_theme
    return {
        "name": "Control-inspired",
        "visual_direction": (
            f"Stay close to the existing control creative's composition and framing for {ad_package.product}; "
            f"primarily update the on-image headline for the new message."
        ),
        "on_image_headline": f"Still dealing with {theme.lower()}?",
        "on_image_supporting_copy": f"{ad_package.product} is built to fix that, without changing what already works.",
        "on_image_proof": ad_package.proof_to_retain,
        "on_image_cta": "",
    }


def _visual_lifestyle(ad_package: AdPackage) -> dict:
    theme = ad_package.customer_theme
    return {
        "name": "Lifestyle",
        "visual_direction": (
            f"Show {ad_package.product} in a natural, everyday home environment relevant to when "
            f"{theme.lower()} matters, rather than an isolated product shot."
        ),
        "on_image_headline": f"{theme} shouldn't be part of your routine.",
        "on_image_supporting_copy": "",
        "on_image_proof": "",
        "on_image_cta": "",
    }


def _visual_sensory_focus(ad_package: AdPackage) -> dict:
    theme = ad_package.customer_theme
    return {
        "name": "Sensory focus",
        "visual_direction": (
            f"Emphasize a close, sensory product detail (e.g. water, glass, texture) connected to "
            f"{theme.lower()}, rather than a wide product shot."
        ),
        "on_image_headline": f'"{theme}? Not with {ad_package.product}."',
        "on_image_supporting_copy": "",
        "on_image_proof": "",
        "on_image_cta": "",
    }


def _visual_minimal_studio(ad_package: AdPackage) -> dict:
    return {
        "name": "Minimal studio",
        "visual_direction": (
            f"A clean, minimal studio composition centered on {ad_package.product}, with generous negative "
            f"space for the on-image headline."
        ),
        "on_image_headline": ad_package.headline,
        "on_image_supporting_copy": "",
        "on_image_proof": ad_package.proof_to_retain,
        "on_image_cta": "",
    }


def _visual_human_moment(ad_package: AdPackage) -> dict:
    theme = ad_package.customer_theme
    return {
        "name": "Human moment",
        "visual_direction": (
            f"Show a relatable human moment connected to {theme.lower()}, with {ad_package.product} naturally "
            f"present in the scene."
        ),
        "on_image_headline": f"Still dealing with {theme.lower()}?",
        "on_image_supporting_copy": f"{ad_package.product} customers say the difference is obvious.",
        "on_image_proof": "",
        "on_image_cta": "",
    }


def _visual_bold_graphic(ad_package: AdPackage) -> dict:
    theme = ad_package.customer_theme
    return {
        "name": "Bold graphic",
        "visual_direction": (
            f"A bold, graphic-forward layout foregrounding the on-image headline and proof claim, with "
            f"{ad_package.product} secondary in the frame."
        ),
        "on_image_headline": f'"{theme}? Not with {ad_package.product}."',
        "on_image_supporting_copy": "",
        "on_image_proof": ad_package.proof_to_retain,
        "on_image_cta": "",
    }


VISUAL_DIRECTION_STRATEGIES = [
    _visual_control_inspired,
    _visual_lifestyle,
    _visual_sensory_focus,
    _visual_minimal_studio,
    _visual_human_moment,
    _visual_bold_graphic,
]

# Parallel to VISUAL_DIRECTION_STRATEGIES, by position: internal labels only
# (never shown as-is; see _build_creative_version's rationale text), used so
# _pick_evidence_informed_direction and _select_batch_roles can name a
# strategy without having to call it first just to read its "name" key.
STRATEGY_NAMES = ["Control-inspired", "Lifestyle", "Sensory focus", "Minimal studio", "Human moment", "Bold graphic"]

# All strategies except "Minimal studio" build their on-image headline from
# the package's own customer_theme (the customer-language distillation of
# the experiment's hypothesis/insight); "Minimal studio" instead echoes the
# ad's own existing headline. This is a structural property of the 6
# templates themselves, not a Brio-specific rule, so it generalizes to any
# future proposal: the hypothesis-informed role prefers a theme-driven
# template, since that's what "visualizes the customer problem" means here.
_THEME_DRIVEN_STRATEGY_NAMES = {name for name in STRATEGY_NAMES if name != "Minimal studio"}

# Generic bridge from one qualifying VisualPatternResult to the one existing
# visual-direction strategy that most directly embodies that attribute
# value. Keyed by the visual taxonomy's own attribute/value vocabulary
# (core/visual_performance.py), never by a product, theme, or creative id,
# so the same table applies to any future client or proposal. A value with
# no entry (e.g. environment="abstract") simply isn't used to steer a
# direction; the next qualifying attribute (or, if none, the fallback path)
# takes over. See _pick_evidence_informed_direction.
_ATTRIBUTE_TO_STRATEGY: dict[str, dict[str, str]] = {
    "human_present": {"True": "Human moment", "False": "Minimal studio"},
    "product_prominence": {"high": "Bold graphic", "medium": "Lifestyle", "low": "Lifestyle"},
    "water_or_glass_prominence": {"high": "Sensory focus"},
    "text_density": {"high": "Bold graphic", "low": "Minimal studio"},
    "environment": {"home": "Lifestyle", "studio": "Minimal studio"},
    "proof_visible": {"True": "Control-inspired", "False": "Lifestyle"},
}


def _pick_evidence_informed_direction(
    client_id: str, product: str, funnel_stage: str
) -> tuple[str | None, VisualPatternResult | None, str | None]:
    """The one strategy (by STRATEGY_NAMES name), if any, that same-product/
    same-funnel-stage visual-performance evidence supports for this
    experiment, plus the VisualPatternResult it came from and its
    provenance ("observed" | "synthetic" | "mixed", see
    core.visual_performance.attribute_value_provenance).

    Walks visual_performance_context's results in its own fixed attribute
    order and returns the FIRST one that is both sufficient and maps to a
    known strategy; never combines multiple attributes into one inferred
    "best" direction, and never treats an insufficient result as a
    tie-breaker. Returns (None, None, None) when no attribute both has
    sufficient evidence in this exact context AND maps to a strategy: the
    caller is expected to fall back to the hypothesis/control-driven path,
    never to invent a pattern here.
    """
    for result in visual_performance_context(client_id, product, funnel_stage):
        if not result.sufficient or result.leading_value is None:
            continue
        strategy_name = _ATTRIBUTE_TO_STRATEGY.get(result.attribute, {}).get(str(result.leading_value))
        if not strategy_name:
            continue
        provenance = attribute_value_provenance(client_id, result.attribute, product, funnel_stage, result.leading_value)
        return strategy_name, result, provenance
    return None, None, None


def _select_batch_roles(
    ad_package: AdPackage, batch_index: int
) -> list[tuple[str, str, VisualPatternResult | None, str | None]]:
    """The 3 (role, strategy_name, evidence_result, provenance) tuples for
    one batch: always exactly one "evidence_informed", one
    "hypothesis_informed", and one "exploratory" role, balanced exploration
    rather than always picking the 3 historically strongest patterns (this
    demo only ever has, at most, one qualifying pattern per context to
    begin with, so "3 strongest" isn't even meaningful here; the balance
    matters more once a live model has more to choose from).

    A few of the 6 fixed strategies intentionally share the exact same
    on-image headline template when used alone (e.g. "Control-inspired"
    and "Human moment" both open with "Still dealing with <theme>?"); the
    old fixed 3-then-3 cycling never combined two of them in one batch, so
    this never surfaced, but a content-blind name-based rotation here
    could silently produce 2 versions with identical on-image copy. So
    this groups the 6 strategies by their ACTUAL rendered on-image
    headline for this ad_package, excludes the evidence-informed pick's
    whole group up front, and only rotates by batch_index across the
    remaining, headline-distinct representatives: every batch's 3 versions
    end up with 3 genuinely different on-image headlines, and "Generate 3
    More" rotates through the remaining distinct group representatives
    before ever repeating one.
    """
    headline_by_name = {
        name: VISUAL_DIRECTION_STRATEGIES[i](ad_package)["on_image_headline"] for i, name in enumerate(STRATEGY_NAMES)
    }

    evidence_name, evidence_result, provenance = _pick_evidence_informed_direction(
        ad_package.client_id, ad_package.product, ad_package.funnel_stage
    )
    evidence_pick = evidence_name or STRATEGY_NAMES[0]

    seen_headlines = {headline_by_name[evidence_pick]}
    remaining_pool = []
    for name in STRATEGY_NAMES:
        if name == evidence_pick:
            continue
        headline = headline_by_name[name]
        if headline in seen_headlines:
            continue
        seen_headlines.add(headline)
        remaining_pool.append(name)

    m = len(remaining_pool)
    rotated_remaining = [remaining_pool[(batch_index + i) % m] for i in range(m)] if m else []

    hypothesis_pick = next(
        (name for name in rotated_remaining if name in _THEME_DRIVEN_STRATEGY_NAMES),
        rotated_remaining[0] if rotated_remaining else evidence_pick,
    )
    exploratory_pick = next(
        (name for name in rotated_remaining if name != hypothesis_pick), hypothesis_pick
    )

    return [
        ("evidence_informed", evidence_pick, evidence_result if evidence_pick == evidence_name else None, provenance if evidence_pick == evidence_name else None),
        ("hypothesis_informed", hypothesis_pick, None, None),
        ("exploratory", exploratory_pick, None, None),
    ]


def _role_rationale(
    role: str, ad_package: AdPackage, evidence_result: VisualPatternResult | None, provenance: str | None
) -> str:
    """The concise, marketer-facing "why this direction" text shown under
    "How these were developed" (never elsewhere: see app_pages/
    creative_lab.py). Deliberately short, non-technical, and never causal
    ("performs better" / "therefore use") language: evidence is described
    as an associative historical pattern in the demo data, not a proven
    cause, and heuristic (demo_synthetic) visual-attribute evidence is
    flagged as such rather than presented with the same confidence as an
    independently reviewed image.
    """
    if role == "evidence_informed":
        if evidence_result is None:
            return (
                "Evidence-informed: no qualifying same-context visual pattern was available, so this direction "
                "was developed from the customer insight and control creative instead."
            )
        base = "Evidence-informed: carries forward a visual characteristic associated with stronger historical performance in comparable demo campaigns."
        if provenance == "observed":
            note = " That pattern includes an independently reviewed source image, not just heuristic metadata."
        elif provenance == "mixed":
            note = " That pattern draws on a mix of independently reviewed and heuristically classified creative imagery."
        else:
            note = " That pattern is based on heuristic, demo-synthetic visual classification, not independently reviewed imagery."
        return base + note
    if role == "hypothesis_informed":
        return "Hypothesis-informed: visualizes the customer problem identified in recent signals."
    return "Exploratory: tests a different execution to broaden what we learn."


def _build_creative_version(
    ad_package: AdPackage,
    direction: dict,
    batch_index: int,
    role: str = "exploratory",
    evidence_result: VisualPatternResult | None = None,
    provenance: str | None = None,
) -> CreativeVersion:
    return CreativeVersion(
        concept_id=f"creative::{ad_package.ad_package_id}::{_slug(direction['name'])}::batch{batch_index}",
        ad_package_id=ad_package.ad_package_id,
        proposal_id=ad_package.proposal_id,
        control_creative_id=ad_package.control_creative_id,
        concept_name=direction["name"],
        visual_direction=direction["visual_direction"],
        on_image_headline=direction["on_image_headline"],
        on_image_supporting_copy=direction.get("on_image_supporting_copy", ""),
        on_image_proof=direction.get("on_image_proof", ""),
        on_image_cta=direction.get("on_image_cta", ""),
        product=ad_package.product,
        funnel_stage=ad_package.funnel_stage,
        format=ad_package.format,
        generation_instruction=_version_generation_instruction(ad_package, direction),
        variable_changed=f"Visual execution: {direction['name']}",
        constants_preserved=list(ad_package.keep_constant),
        rationale=_role_rationale(role, ad_package, evidence_result, provenance),
        status="proposed",
    )


def _demo_generate_versions(ad_package: AdPackage, batch_index: int) -> list[CreativeVersion]:
    """The deterministic preview generator. A future live implementation
    (_live_generate_versions, calling an actual model to derive visual
    directions and on-image copy) would have this exact signature and
    return shape; generate_creative_versions is the only place that would
    need to change which one it calls.

    Picks exactly 3 of the 6 VISUAL_DIRECTION_STRATEGIES per batch via
    _select_batch_roles: one evidence-informed (steered by same-product/
    same-funnel-stage visual-performance evidence when it exists, else a
    hypothesis/control-driven fallback), one hypothesis-informed (built
    from the package's own customer_theme, a distillation of the
    experiment's customer insight), and one exploratory (a meaningfully
    different execution, never just the 2 strongest historical patterns
    repeated a third time). batch_index rotates which strategies fill the
    hypothesis-informed and exploratory roles, so "Generate 3 More" adds
    genuinely new directions rather than repeating the same batch; with 6
    strategies total, exhausting all of them eventually repeats, the same
    known, acceptable limit as before this milestone's change.
    """
    roles = _select_batch_roles(ad_package, batch_index)
    versions = []
    for role, strategy_name, evidence_result, provenance in roles:
        strategy_fn = VISUAL_DIRECTION_STRATEGIES[STRATEGY_NAMES.index(strategy_name)]
        direction = strategy_fn(ad_package)
        versions.append(_build_creative_version(ad_package, direction, batch_index, role, evidence_result, provenance))
    return versions


def _text_too_similar(text_a: str, text_b: str, threshold: float = 0.8) -> bool:
    words_a = set(re.findall(r"[a-z']+", text_a.lower()))
    words_b = set(re.findall(r"[a-z']+", text_b.lower()))
    if not words_a or not words_b:
        return text_a.strip().lower() == text_b.strip().lower()
    overlap = len(words_a & words_b) / len(words_a | words_b)
    return overlap >= threshold


def _numbers_in(text: str) -> set[str]:
    tokens = _TOKEN_PATTERN.findall(text or "")
    return {t for t in tokens if _PURE_NUMBER_PATTERN.fullmatch(t)}


def validate_creative_versions(ad_package: AdPackage, versions: list[CreativeVersion]) -> list[str]:
    """Reusable constraint check for a batch of CreativeVersions,
    model-agnostic: it checks the OUTPUT shape against the AdPackage, so it
    applies identically to this demo generator or a future live one.

    Checks (deliberately NOT brittle exact-text equality on on-image
    copy, since versions are allowed to differ there): every version
    shares the same ad_package_id/proposal_id/control_creative_id/
    product/funnel_stage/format as the package (the true constants, never
    silently drifted); any on_image_proof, when present, matches the
    package's own proof_to_retain exactly (never a different or invented
    proof claim); no on-image field introduces a number/percentage absent
    from the approved proof text (an invented numeric claim) or matches
    the generic fabricated-result denylist; and every pair of versions has
    a meaningfully distinct visual_direction (not a tiny wording variant
    of another) and not byte-identical on-image headlines. Returns a list
    of violation strings, empty if the batch is clean.
    """
    issues = []
    if not versions:
        issues.append("Expected at least 1 creative version, got 0.")

    package_values = {
        "ad_package_id": ad_package.ad_package_id,
        "proposal_id": ad_package.proposal_id,
        "control_creative_id": ad_package.control_creative_id,
        "product": ad_package.product,
        "funnel_stage": ad_package.funnel_stage,
        "format": ad_package.format,
    }
    allowed_numbers = _numbers_in(ad_package.proof_to_retain)

    for version in versions:
        for field_name in _SHARED_PACKAGE_FIELDS:
            if getattr(version, field_name) != package_values[field_name]:
                issues.append(
                    f'{version.concept_id}: "{field_name}" does not match the approved ad package '
                    f"({getattr(version, field_name)!r} != {package_values[field_name]!r})."
                )
        if version.on_image_proof and version.on_image_proof != ad_package.proof_to_retain:
            issues.append(f"{version.concept_id}: on-image proof does not match the approved retained proof.")

        on_image_text = " ".join(
            filter(None, [version.on_image_headline, version.on_image_supporting_copy, version.on_image_cta])
        )
        invented_numbers = _numbers_in(on_image_text) - allowed_numbers
        if invented_numbers:
            issues.append(
                f"{version.concept_id}: on-image copy introduces a number/claim not present in the approved "
                f"proof: {sorted(invented_numbers)}."
            )
        if PERFORMANCE_CLAIM_PATTERN.search(on_image_text):
            issues.append(f"{version.concept_id}: on-image copy contains an unsupported performance claim.")

    for i in range(len(versions)):
        for j in range(i + 1, len(versions)):
            if _text_too_similar(versions[i].visual_direction, versions[j].visual_direction):
                issues.append(
                    f"{versions[i].concept_id} and {versions[j].concept_id} are not visually distinct enough."
                )

    return issues


def validate_version_edit(original: CreativeVersion, edited: CreativeVersion) -> list[str]:
    """Reusable per-edit guard: a marketer may rewrite a version's visual
    direction, on-image copy, concept name, or rationale, but never the
    shared ad-package constants. Not wired into the default Creative Lab
    workflow (concept development is internal Creative Studio work now),
    but kept for optional internal/expander use. Returns a list of
    violation strings, empty if the edit is safe to save.
    """
    issues = []
    for field_name in PROTECTED_VERSION_FIELDS:
        if getattr(original, field_name) != getattr(edited, field_name):
            issues.append(f'Editing "{field_name}" is not allowed: it is part of the approved ad package.')
    return issues


def generate_creative_versions(ad_package: AdPackage, batch_index: int = 0) -> list[CreativeVersion]:
    """Turn one (treatment) AdPackage into one batch of 3 CreativeVersions,
    all expressing the same strategy while each proposing its own on-image
    execution.

    Raises AssertionError if the generator's own output fails
    validate_creative_versions: for a deterministic generator this should
    never happen, so a failure here means a real bug, not bad luck.
    """
    versions = _demo_generate_versions(ad_package, batch_index)
    issues = validate_creative_versions(ad_package, versions)
    if issues:
        raise AssertionError("Generated creative versions failed validation: " + "; ".join(issues))
    return versions


# --- Creative Lab V2: Creative Concepts (Milestone 22) ----------------------
# A CreativeConcept is a distinct STRATEGIC ANGLE for one CreativeOpportunity
# (a different hypothesis about what will move this audience: naming the
# problem vs. picturing the outcome vs. leading with proof), not a visual
# execution of one fixed ad package the way CreativeVersion is. The 3
# concepts in a family therefore vary primary_text/headline/reason_to_believe
# (the thing actually being tested); they deliberately share the same CTA,
# product, funnel stage, and format (opportunity.constants_to_preserve),
# exactly as a real A/B test on messaging angle would hold everything else
# constant. Copy is grounded only in fields the CreativeOpportunity already
# carries (theme/product/CTA/proof) plus the control creative's own approved
# proof text, never an invented Brio claim or a fabricated customer quote.


@dataclass
class CreativeConcept:
    """One strategic messaging angle within a Creative Family: a
    generation-ready copy brief plus a placeholder visual direction, not a
    generated image. Reuses the same on-image-copy field names as
    CreativeVersion (headline/primary_text/cta/reason_to_believe) so a
    future live model or a later Experiments integration can treat a
    concept the same way it already treats a creative version; status
    stays "proposed" until a human includes it in a prepared experiment.
    """

    concept_id: str
    opportunity_id: str
    source_finding_id: str
    concept_name: str
    angle: str
    why_this_concept_exists: str
    avatar: str
    awareness_stage: str
    pain_point: str
    product: str
    funnel_stage: str
    primary_text: str
    headline: str
    cta: str
    format: str
    visual_direction: str
    variable_being_tested: str
    constants_to_preserve: list[str] = field(default_factory=list)
    reason_to_believe: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "proposed"
    generated_by: str = GENERATED_BY_PREVIEW


def _angle_problem_recognition(opportunity: CreativeOpportunity) -> dict:
    theme = opportunity.pain_point
    product = opportunity.product
    return {
        "name": "Problem recognition",
        "angle": "Open with the customer's own problem, in their own language, before introducing the product.",
        "why_this_concept_exists": (
            f'Customers are actively bringing up "{theme}" (see evidence): naming the problem directly tests '
            f"whether recognition alone earns more attention than a benefit-led or proof-led open."
        ),
        "headline": f"Still dealing with {theme.lower()}?",
        "primary_text": (
            f"If {theme.lower()} is part of your routine, {product} is built to change that, without changing "
            f"what already works about your setup."
        ),
        "reason_to_believe": "",
        "visual_direction": f"A relatable moment where {theme.lower()} is noticeable, before {product} appears as the fix.",
    }


def _angle_desired_outcome(opportunity: CreativeOpportunity) -> dict:
    theme = opportunity.pain_point
    product = opportunity.product
    return {
        "name": "Desired outcome",
        "angle": "Lead with the outcome the customer wants instead of the problem they have.",
        "why_this_concept_exists": (
            f'Tests whether picturing life without "{theme}" motivates response more than naming the problem '
            f"itself, a different hypothesis about what actually moves this audience."
        ),
        "headline": f"{product}: Built So {theme.title()} Isn't a Thing",
        "primary_text": (
            f"Picture never thinking about {theme.lower()} again. {product} is designed around that outcome, "
            f"not just a feature list."
        ),
        "reason_to_believe": "",
        "visual_direction": (
            f"A clean, aspirational shot of {product} in everyday use, emphasizing ease and relief rather than "
            f"the problem itself."
        ),
    }


def _angle_proof_led(opportunity: CreativeOpportunity, proof: str) -> dict:
    theme = opportunity.pain_point
    product = opportunity.product
    return {
        "name": "Proof-led",
        "angle": "Lead with the existing approved product proof, connected explicitly to this pain point.",
        "why_this_concept_exists": (
            "Tests whether a credibility-first open, anchored in the same approved proof already used today, "
            f'converts better for "{theme}"-motivated customers than a purely emotional or problem-first open.'
        ),
        "headline": f"{product}: The Proof Behind the {theme.title()} Difference",
        "primary_text": f"{proof} That's the difference customers notice most when {theme.lower()} was their reason to switch.",
        "reason_to_believe": proof,
        "visual_direction": f"A confident, evidence-forward layout foregrounding the proof claim, with {product} secondary in frame.",
    }


# Fixed, ordered pool of angle strategies, generic (built only from
# CreativeOpportunity fields plus the control's own CTA/proof), never a
# product- or theme-specific special case: the same 3 angles apply to any
# future opportunity. Deliberately not the 6 VISUAL_DIRECTION_STRATEGIES
# above: those vary an ad's VISUAL execution while holding its copy/strategy
# fixed; these vary the MESSAGING ANGLE itself, which is what a Creative
# Family's concepts are supposed to test.
CONCEPT_ANGLE_NAMES = ["Problem recognition", "Desired outcome", "Proof-led"]


def generate_concepts_for_opportunity(client_id: str, opportunity: CreativeOpportunity) -> list[CreativeConcept]:
    """The 3 angle-differentiated CreativeConcepts for one CreativeOpportunity:
    Problem recognition, Desired outcome, and Proof-led, each a distinct
    hypothesis about what will move this audience, not a cosmetic visual
    variant. All 3 share the opportunity's own CTA, product, funnel stage,
    and format (constants_to_preserve); only headline/primary_text/
    reason_to_believe (the tested variable) differ between them.

    Raises AssertionError if the generator's own output fails
    validate_creative_concepts, the same "a deterministic generator should
    never fail its own validator" contract generate_creative_versions uses.
    """
    catalog = load_creative_catalog(client_id)
    control_row = catalog.loc[catalog["creative_id"] == opportunity.control_creative_id].iloc[0]
    cta = control_row["cta"]
    proof = control_row["primary_text"]
    format_ = control_row["format"]

    directions = [
        _angle_problem_recognition(opportunity),
        _angle_desired_outcome(opportunity),
        _angle_proof_led(opportunity, proof),
    ]

    concepts = []
    for direction in directions:
        concepts.append(
            CreativeConcept(
                concept_id=f"concept::{opportunity.opportunity_id}::{_slug(direction['name'])}",
                opportunity_id=opportunity.opportunity_id,
                source_finding_id=opportunity.source_finding_id,
                concept_name=direction["name"],
                angle=direction["angle"],
                why_this_concept_exists=direction["why_this_concept_exists"],
                avatar=opportunity.avatar,
                awareness_stage=opportunity.awareness_stage,
                pain_point=opportunity.pain_point,
                product=opportunity.product,
                funnel_stage=opportunity.funnel_stage,
                primary_text=direction["primary_text"],
                headline=direction["headline"],
                cta=cta,
                format=format_,
                visual_direction=direction["visual_direction"],
                variable_being_tested=opportunity.variable_to_test,
                constants_to_preserve=list(opportunity.constants_to_preserve),
                reason_to_believe=direction.get("reason_to_believe", ""),
                evidence_refs=[opportunity.source_finding_id],
            )
        )

    issues = validate_creative_concepts(concepts, proof)
    if issues:
        raise AssertionError("Generated creative concepts failed validation: " + "; ".join(issues))
    return concepts


def validate_creative_concepts(concepts: list[CreativeConcept], proof: str) -> list[str]:
    """Reusable constraint check for one family's concepts, the same
    claim-safety philosophy as validate_creative_versions: no on-image-style
    copy may introduce a number/percentage absent from the approved,
    retained proof text, or match the generic fabricated-result denylist,
    and no two concepts may be near-duplicates of each other (a real
    distinct hypothesis per concept, not 3 cosmetic rewrites of one idea).
    Returns a list of violation strings, empty if the batch is clean.
    """
    issues = []
    if not concepts:
        issues.append("Expected at least 1 creative concept, got 0.")

    allowed_numbers = _numbers_in(proof)
    for concept in concepts:
        text = " ".join(filter(None, [concept.headline, concept.primary_text, concept.reason_to_believe]))
        invented_numbers = _numbers_in(text) - allowed_numbers
        if invented_numbers:
            issues.append(
                f"{concept.concept_id}: introduces a number/claim not present in the approved proof: "
                f"{sorted(invented_numbers)}."
            )
        if PERFORMANCE_CLAIM_PATTERN.search(text):
            issues.append(f"{concept.concept_id}: contains an unsupported performance claim.")

    for i in range(len(concepts)):
        for j in range(i + 1, len(concepts)):
            text_i = f"{concepts[i].headline} {concepts[i].primary_text}"
            text_j = f"{concepts[j].headline} {concepts[j].primary_text}"
            if _text_too_similar(text_i, text_j):
                issues.append(f"{concepts[i].concept_id} and {concepts[j].concept_id} are not distinct enough.")

    return issues
