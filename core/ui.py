"""Shared presentation layer (Milestone 18): a small set of Streamlit
primitives so every page stops inventing its own visual language, not a
frontend framework. Every page should call `inject_base_styles()` once,
near the top, then reach for these helpers instead of raw `st.container`/
`st.markdown` CSS whenever the same shape recurs across pages.

Deliberately thin: a primitive only exists here if at least two pages
actually need it. Anything genuinely page-specific (the Experiments
performance matrix, Creative Lab's creative slot) stays in its own page
file and just uses these primitives for structure (page_header, card,
badge, muted) rather than reinventing spacing/borders/captions locally.

Streamlit in this project's installed version (1.37) has no per-container
`key`/custom-class hook, so a "card level" is expressed through structure
(bordered vs. borderless, an optional accent strip) and typographic
weight, never a fragile bespoke color per instance. `inject_base_styles`
injects ONE global stylesheet, targeting Streamlit's own stable
`data-testid` attributes (the same kind of selector this project's pages
already used individually, e.g. the old per-page `EQUAL_HEIGHT_CARD_CSS`
blocks this module replaces), never a JS/component hack.
"""
from contextlib import contextmanager
from typing import Callable

import streamlit as st

# One shared accent color, replacing the same hex literal ("#2f6fed")
# copy-pasted across overview.py/signals.py/intelligence.py/experiments.py.
ACCENT_COLOR = "#2f6fed"

MAX_CONTENT_WIDTH_PX = 1180

# A small spacing scale (Part 4): reach for these instead of an ad hoc
# st.write("") blank line or a stray st.divider() to create breathing room.
SPACE_XS = "0.25rem"
SPACE_SM = "0.5rem"
SPACE_MD = "1rem"
SPACE_LG = "1.75rem"

_BASE_CSS = f"""
<style>
/* Part 4: one consistent max content width + page padding, instead of
   layout="wide" stretching every page edge-to-edge on a large monitor. */
.block-container {{
    max-width: {MAX_CONTENT_WIDTH_PX}px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}}

/* Part 5/9: softened, consistent corners on every bordered container and
   expander, instead of Streamlit's sharper default, so cards/expanders
   read as one visual family. */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 10px;
}}
/* A card given a fixed height (a row of cards that should align) pins its
   last element to the bottom instead of leaving it wherever content
   happens to end; a no-op for any card with no fixed height. Replaces the
   identical CSS block that used to be copy-pasted in overview.py and
   intelligence.py separately. */
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {{
    height: 100%;
    display: flex;
    flex-direction: column;
}}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] > *:last-child {{
    margin-top: auto;
}}
/* Milestone 22 UX correction: equal-height card ROWS (e.g. Creative Lab's
   3-concept comparison row, Experiments' creative gallery), not just a
   card given an explicit fixed height. The rule above only pins a card's
   last element to the bottom once that card already has a real height to
   fill; these rules establish that real height by making every level
   between one st.columns() row (stHorizontalBlock > column >
   stVerticalBlock > stVerticalBlockBorderWrapper, confirmed against the
   installed frontend bundle) a flex container/item that stretches to the
   row's tallest natural-height sibling, so no pixel number is ever
   hardcoded and longer copy simply makes every card in that row taller
   together. Scoped to a bordered card that is a column's own top-level
   content (a plain, card-less column, e.g. a KPI row, is untouched, since
   it has no stVerticalBlockBorderWrapper for this to target). */
div[data-testid="stHorizontalBlock"] {{
    align-items: stretch;
}}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
    display: flex;
    flex-direction: column;
}}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div[data-testid="stVerticalBlock"] {{
    flex: 1;
    display: flex;
    flex-direction: column;
}}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] div[data-testid="stVerticalBlockBorderWrapper"] {{
    flex: 1;
    display: flex;
    flex-direction: column;
}}
details[data-testid="stExpander"] {{
    border: 1px solid rgba(127, 127, 127, 0.18) !important;
    border-radius: 8px;
    background: rgba(127, 127, 127, 0.035);
}}
details[data-testid="stExpander"] summary {{
    font-size: 0.9rem;
    opacity: 0.85;
}}

/* Part 2/7: the quiet badge/provenance primitive. Milestone 21: sized up
   from an easy-to-miss 0.7rem/1px-9px ("tiny metadata") to a genuine,
   scannable part of the hierarchy (~13-14px, more breathing room) while
   staying visually secondary to the headline/finding beneath it - never
   a CTA-sized pill. Letter-spacing is reduced from the original 0.03em
   so the larger uppercase text doesn't read as over-spread; line-height
   is set explicitly on the badge itself so every badge (any label
   length) has the same height. Centralized here ONLY: nothing else
   (captions, buttons, other widgets) changes size. */
.ui-badge-row {{ margin: 0.15rem 0 0.4rem 0; line-height: 1.6; }}
.ui-badge {{
    display: inline-block;
    padding: 4px 11px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1.3;
    text-transform: uppercase;
    background: rgba(127, 127, 127, 0.14);
    color: var(--text-color);
    opacity: 0.8;
    margin-right: 6px;
    white-space: nowrap;
}}

/* Part 5: the ONE primary-card accent, a thin top strip, used sparingly
   (the single most important card on a page), never per-row. */
.ui-card-accent {{
    height: 3px;
    border-radius: 2px;
    background: {ACCENT_COLOR};
    opacity: 0.85;
    margin: -0.9rem -0.9rem 0.75rem -0.9rem;
}}

/* Part 12: workflow/progress indicator. */
.ui-steps {{ display: flex; align-items: flex-start; margin: 0.2rem 0 0.4rem 0; flex-wrap: wrap; }}
.ui-step {{ display: flex; flex-direction: column; min-width: 118px; }}
.ui-step-marker {{ font-size: 0.95rem; white-space: nowrap; }}
.ui-step-sub {{ font-size: 0.72rem; opacity: 0.6; margin-top: 1px; }}
.ui-step-connector {{
    display: inline-block; width: 28px; height: 1px; background: var(--text-color);
    opacity: 0.25; margin: 10px 10px 0 10px;
}}

/* Part 9/13: a compact, muted supporting line, for provenance/metadata
   that should read as quieter than a normal st.caption when it sits right
   next to primary content. */
.ui-quiet {{ font-size: 0.82rem; opacity: 0.65; }}

/* Milestone 19, Part 7: the reusable ad preview's own CTA treatment - a
   styled pill, never a real (and so misleadingly disabled-looking)
   st.button, since this preview represents an ad that isn't actually
   clickable in this app. */
.ui-ad-advertiser {{ font-weight: 700; font-size: 0.95rem; margin-bottom: 0.2rem; }}
.ui-ad-cta {{
    display: inline-block;
    padding: 4px 14px;
    border-radius: 6px;
    background: rgba(127, 127, 127, 0.14);
    font-size: 0.8rem;
    font-weight: 600;
    margin-top: 0.3rem;
}}

/* Milestone 20 (UX correction pass), Parts 1/2/11: one consistent button
   treatment for every `st.page_link` in the product - both the sidebar's
   own navigation AND any in-page action (Overview's "Review experiment" /
   "Explore opportunity" / "Develop creative", etc.). st.page_link renders
   as a near-bare text link by default, easy to miss as a control at all;
   this gives it a visible shape and border at rest (never only on hover),
   a subtle accent background on hover, and forces a fixed, uniform
   margin on every instance so a row of sidebar links reads as one evenly
   spaced group regardless of which one happens to be the active page
   (Streamlit's own active-link styling differs from an inactive one, but
   this margin rule is unconditional, so spacing itself never varies). */
[data-testid="stPageLink-NavLink"] {{
    display: flex !important;
    align-items: center;
    padding: 0.4rem 0.7rem !important;
    margin: 0.15rem 0 !important;
    border-radius: 6px !important;
    background: rgba(127, 127, 127, 0.06);
    border: 1px solid rgba(127, 127, 127, 0.14);
    font-weight: 500;
    transition: background 0.12s ease, border-color 0.12s ease;
}}
[data-testid="stPageLink-NavLink"]:hover {{
    background: color-mix(in srgb, {ACCENT_COLOR} 14%, transparent);
    border-color: color-mix(in srgb, {ACCENT_COLOR} 45%, transparent);
}}

/* Same non-negotiable "looks clickable at rest" rule for every native
   st.button, primary or secondary: consistent corner radius across the
   whole product (matching the badges/cards above), never styled
   per-instance per-page. Primary already gets a strong fill from the
   theme's own primaryColor (.streamlit/config.toml); secondary gets a
   slightly firmer border than Streamlit's own default so it still reads
   as a real control next to the page-link buttons above, not just body
   text with a click target. */
button[kind="primary"], button[kind="secondary"] {{
    border-radius: 6px !important;
}}
button[kind="secondary"] {{
    border-color: rgba(127, 127, 127, 0.35) !important;
}}

/* Milestone 20, Part 3: a light per-row separator for the Signal Feed,
   instead of a bordered card per signal (too heavy for supporting
   evidence) or a bare list with no visual rhythm at all. */
.ui-feed-divider {{
    border-bottom: 1px solid rgba(127, 127, 127, 0.14);
    margin: 0.6rem 0;
}}

/* Milestone 20, Part 5: a moderately-sized (not enormous) finding number,
   visually noticeable ahead of its own type badge, without competing with
   the finding's own title (the dominant element). */
.ui-finding-number {{
    font-size: 1.3rem;
    font-weight: 700;
    opacity: 0.32;
    line-height: 1.3;
}}
</style>
"""


def inject_base_styles() -> None:
    """Call once near the top of every page, after the title/header. CSS
    injection is idempotent (Streamlit reruns the whole script on every
    interaction, so this runs again each time; repeating the same <style>
    tag has no adverse effect), so there is no "already injected" guard to
    maintain.
    """
    st.markdown(_BASE_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None, badges: list[str] | None = None) -> None:
    """PAGE IDENTITY (Part 3's hierarchy, step 1): the title, one optional
    subtitle line, and an optional quiet badge row for provenance (Part 7),
    replacing the 2-3 stacked st.caption lines every page used to hand-roll
    independently.
    """
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if badges:
        badge_row(badges)


def section_header(label: str, subtitle: str | None = None, level: str = "section") -> None:
    """A heading with its own optional one-line explanation, used
    consistently instead of some pages pairing st.subheader with a
    caption and others leaving it bare.

    `level="section"` (default) is `st.subheader` (h3): a page's own
    top-level sections (e.g. "Insights Brief," "Supporting analysis").
    `level="subsection"` is one step down (h4, via markdown, since
    Streamlit has no native `st.subsubheader`): a named unit WITHIN a
    section (e.g. "Customer language vs. current marketing" under
    "Supporting analysis") that still needs to read as a real heading,
    not bold body text, without competing with the section above it.
    """
    if level == "subsection":
        st.markdown(f"#### {label}")
    else:
        st.subheader(label)
    if subtitle:
        st.caption(subtitle)


def badge(text: str) -> str:
    """One inline badge span (Part 7): DEMO DATA / AI GENERATED / LIMITED
    EVIDENCE / etc., quiet by design (small, muted, uppercase) rather than
    a loud sentence repeated on every page. Returns markup; use badge_row
    to actually render one or more badges in one line.
    """
    return f'<span class="ui-badge">{text}</span>'


def badge_row(labels: list[str]) -> None:
    """Renders one or more badges on a single line."""
    st.markdown(f'<div class="ui-badge-row">{"".join(badge(label) for label in labels)}</div>', unsafe_allow_html=True)


def muted(text: str) -> None:
    """A quiet, de-emphasized line (Part 2's "muted/supporting text"):
    functionally close to st.caption, but signals at the call site that
    this text is DELIBERATELY secondary next to primary content it sits
    beside (evidence, metadata, provenance detail), rather than st.caption
    used for an ordinary subtitle.
    """
    st.markdown(f'<div class="ui-quiet">{text}</div>', unsafe_allow_html=True)


@contextmanager
def card(level: str = "standard", height: int | None = None):
    """One of 3 card levels (Part 5), replacing bare `st.container(border=
    True)` used identically everywhere regardless of importance:

    - "primary": the single most important object on the page (a top
      finding, a results hero, a recommendation). Bordered, plus a thin
      accent strip, used sparingly (never for every item in a grid).
    - "standard": a normal card in a repeated grid (a creative, a finding,
      an experiment row). Bordered, plain.
    - "quiet": supporting/evidence/metadata content that should recede,
      never compete with primary content. No border at all.

    `height`, if given, fixes the card's height (for a row of cards that
    should align, e.g. findings of uneven length); the base stylesheet
    then pins the card's last element to the bottom rather than leaving a
    gap. Usage: `with ui.card("primary"): ...` exactly like `st.container`.
    """
    if level == "quiet":
        with st.container(border=False, height=height):
            yield
    elif level == "primary":
        with st.container(border=True, height=height):
            st.markdown('<div class="ui-card-accent"></div>', unsafe_allow_html=True)
            yield
    else:
        with st.container(border=True, height=height):
            yield


def progress_steps(steps: list[tuple[str, str]], current_key: str, subtext: dict[str, str] | None = None) -> None:
    """A workflow/progress indicator (Part 2 and Part 12): `steps` is a
    list of (key, label) pairs in order; `current_key` marks which one is
    active. A completed step gets a checkmark, the current step a filled
    dot in the theme's accent color, a future step a plain number at
    reduced opacity. `subtext`, if given, adds one small explanatory
    phrase under a step's own label (e.g. "Found the angle"), keyed by the
    same step key; a step with no entry just shows its label alone, so
    callers can annotate only the steps worth annotating.
    """
    subtext = subtext or {}
    keys = [key for key, _ in steps]
    current_index = keys.index(current_key)

    parts = ['<div class="ui-steps">']
    for i, (key, label) in enumerate(steps):
        if i < current_index:
            marker, style = "✓", "opacity:0.75; color:var(--text-color); font-weight:500;"
        elif i == current_index:
            marker, style = "●", f"color:{ACCENT_COLOR}; font-weight:700;"
        else:
            marker, style = str(i + 1), "opacity:0.4; color:var(--text-color); font-weight:400;"
        sub = subtext.get(key)
        parts.append(
            '<div class="ui-step">'
            f'<span class="ui-step-marker" style="{style}">{marker}&nbsp;{label}</span>'
            + (f'<span class="ui-step-sub">{sub}</span>' if sub else "")
            + "</div>"
        )
        if i < len(steps) - 1:
            parts.append('<span class="ui-step-connector"></span>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def metric_row(items: list[tuple[str, str]]) -> None:
    """A row of `st.metric` widgets from (label, value) pairs, replacing
    the repeated `cols = st.columns(n); cols[0].metric(...); cols[1]...`
    boilerplate that showed up independently on Overview, Creative Lab,
    and Experiments. Delta coloring is intentionally not exposed here:
    callers that need a delta render it as a separate muted caption
    instead (see agents/performance/engine.py's own reasoning for why this
    product avoids Streamlit's built-in green/red delta color), so this
    stays a plain, neutral metric strip.
    """
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def empty_state(message: str, caption: str | None = None) -> None:
    """A consistent "nothing here yet" block (Part 2), replacing ad hoc
    st.info/st.caption calls that varied their wording/tone per page.
    """
    st.info(message)
    if caption:
        st.caption(caption)


def render_ad_preview(
    *,
    advertiser_name: str,
    headline: str,
    image_path: str | None = None,
    primary_text: str = "",
    description: str = "",
    cta: str = "",
    provenance: str | list[str] | None = None,
    compact: bool = False,
    image_width: int | None = None,
) -> None:
    """A reusable, platform-neutral, social-feed-style ad preview
    (Milestone 19, Part 7): advertiser name, primary text, image,
    headline, description, and a CTA treatment, in that order, so an ad
    reads as an AD rather than a bare image asset. Deliberately NOT a
    pixel-accurate Meta/Facebook clone: a marketing-workflow preview, not
    a social-platform simulator.

    Pure presentation: every field is data the caller already has (an
    AdPackage's own primary_text/headline/description/cta plus whatever
    image path it already resolved) - this function knows nothing about
    Brio, Meta, or any specific client. `provenance`, if given (one string,
    or a list when the ad's copy and its image have genuinely separate
    provenance, e.g. "Observed ad copy (Meta Ads Library)" and "Public-ad-
    observed source creative" can both be true of the same ad without
    being the same fact), renders as one quiet line per entry; callers
    must never also imply that PERFORMANCE numbers came from that same
    observed-copy source (this function has no performance fields at all,
    on purpose, to keep that boundary structural, not just a wording
    convention).

    `compact=True` truncates primary_text and shrinks the image, for a
    smaller, secondary rendering (e.g. a side-by-side comparison later on
    Experiments); the default (`compact=False`) is the full, primary
    rendering used when this IS the main object on the page.
    """
    with card("standard"):
        st.markdown(f'<div class="ui-ad-advertiser">{advertiser_name}</div>', unsafe_allow_html=True)
        if primary_text:
            text = primary_text
            if compact and len(text) > 140:
                text = text[:140].rstrip() + "..."
            st.write(text)
        if image_path:
            st.image(image_path, width=image_width or (160 if compact else 320))
        if headline:
            st.markdown(f"**{headline}**")
        if description:
            st.caption(description)
        if cta:
            st.markdown(f'<span class="ui-ad-cta">{cta}</span>', unsafe_allow_html=True)
        if provenance:
            for line in ([provenance] if isinstance(provenance, str) else provenance):
                muted(line)


def render_creative_placeholder(
    *,
    angle_label: str,
    headline: str,
    primary_text: str = "",
    cta: str = "",
    why_this_exists: str = "",
    reason_to_believe: str = "",
    footer: Callable[[], None] | None = None,
) -> None:
    """A polished stand-in for a not-yet-generated creative concept
    (Creative Lab V2): a dashed "image generation added next" box where a
    real creative preview will eventually render, plus the concept's own
    copy (headline, primary text, CTA) so the concept reads as a real,
    considered idea even before an image exists. Never calls an image
    provider and never substitutes a real (existing or generated) asset;
    this is the ONLY visual for a concept until a later milestone
    reconnects live generation.

    Reuses the same card/badge/CTA-pill/muted primitives as render_ad_preview
    rather than inventing a second visual language for "a proposed ad
    without an image yet."

    `footer`, if given, is called last, still INSIDE this card's own
    bordered container (e.g. an "Include in experiment" checkbox): the
    base stylesheet's equal-height-row CSS pins a card's own last child to
    the bottom, so a control rendered here, inside the card, lines up
    across a row of unequal-length concepts; the same control rendered
    AFTER this function returns (outside the card) would not.
    """
    with card("standard"):
        badge_row([angle_label.upper()])
        st.markdown(
            '<div style="border: 1px dashed rgba(127, 127, 127, 0.35); border-radius: 8px; '
            'padding: 1.4rem 1rem; text-align: center; margin-bottom: 0.6rem; opacity: 0.8;">'
            '<div style="font-weight: 600; letter-spacing: 0.04em; font-size: 0.85rem;">CREATIVE PREVIEW</div>'
            '<div class="ui-quiet" style="margin-top: 0.2rem;">Image generation added next</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        if headline:
            st.markdown(f"**{headline}**")
        if primary_text:
            st.write(primary_text)
        if reason_to_believe:
            muted(reason_to_believe)
        if cta:
            st.markdown(f'<span class="ui-ad-cta">{cta}</span>', unsafe_allow_html=True)
        if why_this_exists:
            muted(why_this_exists)
        if footer:
            footer()
