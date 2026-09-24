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
import html
from contextlib import contextmanager
from typing import Callable

import streamlit as st
import streamlit.components.v1 as components

# One shared accent color, replacing the same hex literal ("#2f6fed")
# copy-pasted across overview.py/signals.py/intelligence.py/experiments.py.
ACCENT_COLOR = "#2f6fed"

# Milestone 30: one centralized typeface choice. Atlassian Sans (Jira's
# actual product typeface) is distributed only through Atlassian's own
# authenticated "Mosaic" platform for internal/product use - confirmed
# before choosing anything: atlassian.design states app fonts are
# available for download there, with no public license grant and no
# public CDN, so it is not something this project can adopt. Inter (SIL
# Open Font License 1.1, freely usable, served from Google Fonts) is the
# openly-licensed alternative already widely used to approximate exactly
# this clean, Atlassian-adjacent UI sans, and is the fallback this
# project's own brief named first. Named ONCE, here: trying DM Sans or
# another Google Fonts family later means changing FONT_PRIMARY_NAME and
# the weights in FONT_GOOGLE_FONTS_URL and nothing else - no other file
# in the app names a font.
FONT_PRIMARY_NAME = "Inter"
FONT_GOOGLE_FONTS_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
# Falls back to each OS's own native UI sans (never a generic serif/mono)
# if the Google Fonts request fails for any reason - the interface stays
# readable, just without Inter's specific letterforms.
FONT_PRIMARY_STACK = (
    f"'{FONT_PRIMARY_NAME}', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "Roboto, Helvetica, Arial, sans-serif"
)

MAX_CONTENT_WIDTH_PX = 1180

# A small spacing scale (Part 4): reach for these instead of an ad hoc
# st.write("") blank line or a stray st.divider() to create breathing room.
SPACE_XS = "0.25rem"
SPACE_SM = "0.5rem"
SPACE_MD = "1rem"
SPACE_LG = "1.75rem"

_BASE_CSS = f"""
<style>
/* Milestone 30 (Jira-inspired typography): @import must be the first rule
   in a stylesheet or the browser ignores it - this has to stay the very
   first thing in _BASE_CSS. `.streamlit/config.toml`'s [theme] table only
   accepts the 3 generic families ("sans serif"/"serif"/"monospace") in
   this Streamlit version (1.37); naming an actual font family and loading
   it is only possible here. `--font-primary` is the ONE place the choice
   is centralized: every rule below reads it rather than naming "Inter"
   again, and `--gdg-font-family` repeats it under the specific CSS
   variable name Streamlit's own dataframe grid (glide-data-grid) reads
   for its canvas-rendered text (confirmed present in the installed
   1.37.1 frontend bundle), so Insights' evidence tables pick it up too.
   `html`/`body`/[data-testid="stApp"] are !important because Streamlit's
   own theme already sets a font-family at comparable-or-higher
   specificity; form controls (button/input/select/textarea) need their
   own rule since browsers don't inherit font-family onto them by default,
   regardless of what body sets. */
@import url('{FONT_GOOGLE_FONTS_URL}');
:root {{
    --font-primary: {FONT_PRIMARY_STACK};
    --gdg-font-family: var(--font-primary);
}}
html, body, [data-testid="stApp"] {{
    font-family: var(--font-primary) !important;
}}
button, input, select, textarea {{
    font-family: var(--font-primary) !important;
}}
/* Restrained heading hierarchy (Part 3 of this milestone): Streamlit had
   no heading-size rule anywhere in this stylesheet before, so page
   titles (st.title -> h1, including the sidebar's own title, the same
   element) and st.subheader (h3) simply rendered at Streamlit's own
   default size/weight. Sized down from that default and tightened
   (line-height, a touch of negative tracking on the two largest levels)
   for a calmer, "confident, not shouting" feel; h2 is included for
   completeness even though no page currently uses st.header(). This is
   the only place heading size/weight is set - individual pages never
   override it.

   Milestone 30.1 correction: st.title/st.header/st.subheader render
   through Streamlit's dedicated Heading component, wrapped in
   [data-testid="stHeading"] (confirmed in Heading.tsx, the 1.37.1
   source) - but ui.section_header(level="subsection") does NOT call
   st.subheader; it calls st.markdown(f"#### {{label}}") directly (see
   below), which produces a plain <h4> inside [data-testid=
   "stMarkdownContainer"], never stHeading. Every "####"-based subsection
   header in this app - "What the Strategist found," "Creative
   concepts," "Strategy-wide context," "Insights Brief"'s own
   subsections, "Recent experiment learning" - was therefore invisible to
   the rule above and still rendering at Streamlit's untouched default
   (1.5rem bold Source Sans Pro from reboot.scss), even though the exact
   same font/size/weight was already intended for it. Matching
   [data-testid="stMarkdownContainer"] alongside stHeading fixes this:
   grep confirms st.markdown("#### ...") is the ONLY markdown heading
   syntax used anywhere in this app (no "###"/"##"/"#"), and the selector
   only ever matches a literal h1-h4 TAG, never bold text (<strong>,
   from "**word**"), a badge (a <div>/<span>), or a table - so ordinary
   bold paragraph text and every other component are unaffected. */
:is([data-testid="stHeading"], [data-testid="stMarkdownContainer"]) :is(h1, h2, h3, h4) {{
    font-family: var(--font-primary);
    font-weight: 700;
    line-height: 1.25;
}}
:is([data-testid="stHeading"], [data-testid="stMarkdownContainer"]) h1 {{ font-size: 1.75rem; letter-spacing: -0.01em; }}
:is([data-testid="stHeading"], [data-testid="stMarkdownContainer"]) h2 {{ font-size: 1.4rem; letter-spacing: -0.01em; }}
:is([data-testid="stHeading"], [data-testid="stMarkdownContainer"]) h3 {{ font-size: 1.15rem; font-weight: 600; line-height: 1.3; }}
:is([data-testid="stHeading"], [data-testid="stMarkdownContainer"]) h4 {{ font-size: 1rem; font-weight: 600; line-height: 1.35; }}
/* Metric values (Overview's KPI row): tabular figures so digits align
   column to column when the delta/value changes on a rerun, a genuine
   readability win Inter supports natively; weight/size otherwise
   unchanged from Streamlit's own default so the KPI row's proportions
   (already tuned in an earlier milestone) don't shift. */
[data-testid="stMetricValue"] {{
    font-variant-numeric: tabular-nums;
}}

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
/* Pinned to the bottom ONLY for a card's own content, never for the content
   of a COLUMN. Streamlit renders EVERY vertical block, a column's included,
   as stVerticalBlockBorderWrapper > div > stVerticalBlock (confirmed in the
   1.37 bundle: the block renderer wraps all vertical blocks), so a column's
   content block is column > wrapper > div > stVerticalBlock, not a direct
   child of the column. The Milestone 24 exclusion used a direct-child
   selector and therefore never matched: in a row like Avatar / Awareness
   stage / Pain point, the row stretched every column to the tallest value's
   height and this rule then pushed each shorter column's last child (its
   value) to the BOTTOM, far below its own label. */
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"]:not([data-testid="column"] > div[data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalBlock"]) > *:last-child {{
    margin-top: auto;
}}
/* Milestone 22 UX correction: equal-height card ROWS (e.g. Creative Lab's
   3-concept comparison row, Experiments' creative gallery), not just a
   card given an explicit fixed height. Real DOM (1.37 bundle):
   stHorizontalBlock > column > stVerticalBlockBorderWrapper > div >
   stVerticalBlock > [card: stVerticalBlockBorderWrapper > div >
   stVerticalBlock]. Streamlit's own styles already make the wrapper's inner
   div and stVerticalBlock flex:1 columns; what was missing is the row
   stretching each column and each wrapper (the column's own, and a card
   inside it) to the row's tallest natural-height sibling, so no pixel
   number is ever hardcoded and longer copy simply makes every card in that
   row taller together. A plain, card-less column (a KPI row) is unaffected
   in appearance: its content stays top-aligned because the pin rule above
   excludes column content. */
div[data-testid="stHorizontalBlock"] {{
    align-items: stretch;
}}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
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
    white-space: normal;
    max-width: 100%;
    overflow-wrap: anywhere;
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
   padding/margin on every instance so a row of sidebar links reads as one
   evenly spaced group. */
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
/* Milestone 29.1: every sidebar nav item, including the current page, is a
   real st.page_link - confirmed against Streamlit 1.37.1's own source
   (PageLink.tsx / styled-components.ts) that "is this the current page"
   (isCurrentPage) never reaches the DOM as an attribute/class/aria-marker;
   it's consumed only inside React (an inline background-color computation
   and a boldLabel flag passed to the label's own markdown renderer), so no
   selector here could ever target it directly. core/shell.py instead
   renders an invisible marker element immediately before each page's own
   page_link; :has() (already used the same way for the rhythm marker
   below) lets this stylesheet select the very next nav item from that
   marker's presence, entirely in CSS, with the marker itself taking no
   space. This keys off the SAME component and DOM wrapper as the other
   four items - color/background/font-weight are the only things that
   differ, nothing that affects box size, so no item can ever end up a
   different height or shift its neighbors depending on which page is
   current. (An earlier pass rendered the current page as a hand-styled,
   non-link <div> instead: that div sits in a stMarkdownContainer, which
   carries Streamlit's own -1rem bottom-margin compensation - see the
   rhythm-CSS comment below - that a stPageLink container never gets,
   producing exactly the inconsistent spacing this replaces.)

   Milestone 29.2: a marker precedes EVERY link now, not only the current
   one (core/shell.py), so the sidebar's own element sequence - count,
   type, order - is identical on every page; only which single marker
   carries the "-current-" class changes. `.ui-sidebar-marker` (inactive)
   and `.ui-sidebar-current-marker` (active) are equally invisible; only
   the active one's :has() rule below actually styles anything. Streamlit
   preserves elements created here in app.py (this module's own caller)
   across a page change - traced through Streamlit 1.37.1's own source,
   AppNode.ts's filterMainScriptElements keeps anything tagged with the
   app's constant main-script identity - but a shifting marker position
   still gave the preserved sidebar subtree a different shape run to run,
   which is exactly what forces a positional re-render instead of an
   in-place patch; a fixed slot per link removes that variable. */
.ui-sidebar-marker, .ui-sidebar-current-marker {{
    display: none;
}}
div[data-testid="element-container"]:has(.ui-sidebar-marker),
div[data-testid="element-container"]:has(.ui-sidebar-current-marker) {{
    display: none;
}}
div[data-testid="element-container"]:has(.ui-sidebar-current-marker) + div[data-testid="element-container"] [data-testid="stPageLink-NavLink"] {{
    background: color-mix(in srgb, {ACCENT_COLOR} 16%, transparent) !important;
    border-color: color-mix(in srgb, {ACCENT_COLOR} 40%, transparent) !important;
    border-left: 3px solid {ACCENT_COLOR} !important;
    padding-left: calc(0.7rem - 2px) !important;
    font-weight: 700 !important;
}}

/* Same non-negotiable "looks clickable at rest" rule for every native
   st.button, primary or secondary: consistent corner radius across the
   whole product (matching the badges/cards above), never styled
   per-instance per-page. Primary already gets a strong fill from the
   theme's own primaryColor (.streamlit/config.toml); secondary gets a
   slightly firmer border than Streamlit's own default so it still reads
   as a real control next to the page-link buttons above, not just body
   text with a click target. Milestone 30: medium weight (matching the
   page-link nav rows above), not Streamlit's default regular weight, so
   buttons read with the same "confident, restrained" hand as headings. */
button[kind="primary"], button[kind="secondary"] {{
    border-radius: 6px !important;
    font-weight: 500 !important;
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

/* Milestone 23 UX correction: label/value fields and comparison tables that
   wrap cleanly. One grid element (not one st.columns cell per value), so a
   value that takes two lines never leaves its neighbour's label and value
   far apart, and the grid reflows to fewer columns at narrow widths on its
   own. */
.ui-fields {{
    padding-bottom: 1rem;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
    gap: 1rem 1.5rem;
    align-items: start;
}}
.ui-field-groups {{ display: flex; flex-direction: column; gap: 1.25rem; padding-bottom: 1rem; }}
.ui-field-group + .ui-field-group {{ border-top: 1px solid rgba(127, 127, 127, 0.16); padding-top: 1.25rem; }}
.ui-field-group-title {{
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase;
    opacity: 0.55; margin-bottom: 0.65rem;
}}
.ui-field-group .ui-fields {{ padding-bottom: 0; }}
.ui-field {{ min-width: 0; }}
.ui-field-wide {{ grid-column: 1 / -1; }}
.ui-field-label {{ font-size: 0.82rem; opacity: 0.65; margin-bottom: 0.15rem; }}
.ui-field-value {{ font-size: 1rem; line-height: 1.45; overflow-wrap: anywhere; }}
.ui-field-quiet .ui-field-value {{ font-size: 0.92rem; opacity: 0.85; }}
/* Streamlit styles EVERY markdown <table> with an outer border, a 1px
   border-top on every <tr>, 1px borders on th/td, and a 1rem bottom margin
   (confirmed in the 1.37 bundle). Those are what drew a line ABOVE the
   header of this table; all are reset here (with !important, since the
   emotion rules have equal specificity) and only the header underline and
   the light row separators are drawn, so the table reads as light, not
   boxed in twice inside its card. */
.ui-table-wrap {{ overflow-x: auto; padding-bottom: 1rem; }}
.ui-table {{ width: 100%; border-collapse: collapse; border: none !important; margin: 0 !important; }}
.ui-table tr {{ border: none !important; }}
.ui-table th {{
    text-align: left; font-size: 0.82rem; font-weight: 500; opacity: 0.65;
    padding: 0.3rem 1rem 0.5rem 0 !important; border: none !important;
    border-bottom: 1px solid rgba(127, 127, 127, 0.25) !important; white-space: nowrap;
}}
.ui-table td {{
    padding: 0.75rem 1rem 0.75rem 0 !important; vertical-align: top; border: none !important;
    border-bottom: 1px solid rgba(127, 127, 127, 0.14) !important;
}}
.ui-table tr:last-child td {{ border-bottom: none !important; }}
.ui-table td.ui-num {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
.ui-table td.ui-table-main {{ min-width: 220px; overflow-wrap: anywhere; }}

/* --- Vertical rhythm (opt-in via ui.card(rhythm=True)) ----------------------
   ROOT CAUSE of uneven card spacing, confirmed in the 1.37 bundle: Streamlit
   gives every markdown container margin-bottom:-1rem, to cancel the 1rem
   bottom margin it assumes on the <p> inside. Raw-HTML blocks (muted lines,
   badges, grids) have no <p>, so they lose 1rem after them: the last line
   in a card hugged the bottom border and two adjacent HTML lines had zero
   gap. Inside a rhythm card that -1rem and the <p> margin are both zeroed
   and ONE gap (0.75rem, the vertical block's own flex gap) separates
   elements; padding is equal on all sides. Headings lose their built-in
   padding for the same reason. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) div[data-testid="stVerticalBlock"] {{
    gap: 0.75rem;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) [data-testid="stMarkdownContainer"],
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) [data-testid="stCaptionContainer"] {{
    margin-bottom: 0 !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) [data-testid="stMarkdownContainer"] p,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) [data-testid="stCaptionContainer"] p {{
    margin: 0 !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) [data-testid="stHeading"] :is(h1, h2, h3, h4) {{
    padding: 0 !important;
    margin: 0 !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-marker) :is(.ui-fields, .ui-table-wrap, .ui-field-groups, .ui-callout-wrap) {{
    padding-bottom: 0;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-pad) {{
    padding: 1.15rem 1.25rem !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-accent) {{
    border-top: 3px solid {ACCENT_COLOR} !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ui-rhythm-soft) {{
    background: rgba(127, 127, 127, 0.045);
}}
div[data-testid="element-container"]:has(.ui-rhythm-marker) {{ display: none; }}

/* Page-level text blocks. Because of the -1rem above, each carries its own
   compensating padding-bottom so the visible spacing after it is the
   normal 1rem (note) or a deliberate larger section gap (supporting). */
.ui-note {{ font-size: 0.85rem; line-height: 1.5; opacity: 0.65; padding-bottom: 1rem; }}
.ui-supporting {{ font-size: 1rem; line-height: 1.55; opacity: 0.75; padding-bottom: 1.5rem; }}
/* A primary line with an optional quieter line directly under it. */
.ui-stack-primary {{ line-height: 1.55; }}
.ui-stack-bold {{ font-weight: 600; }}
.ui-stack-secondary {{ margin-top: 0.5rem; font-size: 0.875rem; line-height: 1.5; opacity: 0.7; }}


.ui-ad-field {{ padding-bottom: 1rem; }}
.ui-ad-field-value {{ font-size: 0.95rem; line-height: 1.45; overflow-wrap: anywhere; }}
/* Milestone 26: a lightweight callout (label + text, left accent rule, no
   box) and an expanded "titled summary" block for finding-style content. */
.ui-callout-wrap {{ padding-bottom: 1rem; }}
.ui-callout {{ border-left: 3px solid {ACCENT_COLOR}; padding: 0.1rem 0 0.1rem 0.9rem; }}
.ui-callout-label {{
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase;
    opacity: 0.6; margin-bottom: 0.25rem;
}}
.ui-callout-text {{ font-size: 1rem; line-height: 1.5; }}
.ui-callout-strong .ui-callout-text {{ font-size: 1.15rem; font-weight: 600; line-height: 1.45; }}
.ui-titled-title {{ font-size: 1.25rem; font-weight: 700; line-height: 1.35; }}
.ui-titled-summary {{ font-size: 1rem; line-height: 1.55; margin-top: 0.6rem; }}
.ui-titled-note-label {{
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase;
    opacity: 0.55; margin-top: 1rem; margin-bottom: 0.2rem;
}}
.ui-titled-note {{ font-size: 0.95rem; line-height: 1.5; opacity: 0.8; }}
.ui-numbered-badge .ui-finding-number {{ display: inline-block; vertical-align: middle; margin-right: 0.6rem; }}

/* Milestone 29: a plain safely-escaped paragraph (see ui.safe_paragraph),
   one piece of Evidence (ui.render_evidence_item), and a compact labeled
   multi-part explanation (ui.insight_blocks). */
.ui-paragraph {{ font-size: 1rem; line-height: 1.55; padding-bottom: 1rem; }}
.ui-evidence-label {{ font-weight: 600; margin-bottom: 0.2rem; }}
.ui-evidence-detail {{ font-size: 1rem; line-height: 1.5; margin-bottom: 0.4rem; }}
.ui-evidence-list {{ margin: 0 0 0.4rem 1.15rem; padding: 0; font-size: 1rem; line-height: 1.5; }}
.ui-evidence-list li {{ margin-bottom: 0.2rem; }}
.ui-insight-blocks {{ padding-bottom: 1rem; }}
.ui-insight-block + .ui-insight-block {{ margin-top: 0.85rem; }}
.ui-insight-label {{
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase;
    opacity: 0.6; margin-bottom: 0.2rem;
}}
.ui-insight-text {{ font-size: 0.95rem; line-height: 1.5; }}

/* The one-time scroll-to-top helper's iframe is invisible plumbing. */
div[data-testid="element-container"]:has(iframe[height="0"]) {{
    position: absolute; height: 0; margin: 0; overflow: hidden;
}}
</style>
"""


def inject_base_styles() -> None:
    """Call once near the top of every page, after the title/header. CSS
    injection is idempotent (Streamlit reruns the whole script on every
    interaction, so this runs again each time; repeating the same <style>
    tag has no adverse effect - the browser just applies the same rules
    twice, with no conflict since the values are byte-identical), so there
    is no "already injected" guard to maintain.

    Milestone 29.2: app.py ALSO calls this once, before render_sidebar, so
    the stylesheet is tagged with the app's own main-script identity and
    survives every page navigation (see app.py's own docstring for why);
    each page's own call here is kept too, so a page still looks correct
    even rendered outside app.py (e.g. in a test that loads one page file
    directly), and the two calls together are still just one harmless
    repeated <style> tag per run.
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
def card(level: str = "standard", height: int | None = None, rhythm: bool = False, soft: bool = False):
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

    `rhythm=True` (opt-in, so cards on pages that already look right are
    untouched) applies the shared vertical-rhythm rules in _BASE_CSS: equal
    top/bottom/side padding, one uniform gap between the card's elements,
    Streamlit's own markdown/heading margins neutralized, and, for
    "primary", the accent as a top border instead of a separate strip
    element (whose negative-margin math assumed Streamlit's default padding
    and a 1rem gap). Implemented with a zero-size marker element that the
    CSS keys on via :has() and hides (display:none, so it takes no gap).
    `soft=True` (bordered rhythm cards only) adds a very quiet background
    tint, for compact summary cards stacked on a page.
    """
    if level == "quiet":
        with st.container(border=False, height=height):
            if rhythm:
                st.markdown('<div class="ui-rhythm-marker"></div>', unsafe_allow_html=True)
            yield
    elif level == "primary":
        with st.container(border=True, height=height):
            if rhythm:
                st.markdown('<div class="ui-rhythm-marker ui-rhythm-pad ui-rhythm-accent"></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ui-card-accent"></div>', unsafe_allow_html=True)
            yield
    else:
        with st.container(border=True, height=height):
            if rhythm:
                soft_cls = " ui-rhythm-soft" if soft else ""
                st.markdown(f'<div class="ui-rhythm-marker ui-rhythm-pad{soft_cls}"></div>', unsafe_allow_html=True)
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
    headline: str = "",
    primary_text: str = "",
    cta: str = "",
    why_this_exists: str = "",
    reason_to_believe: str = "",
    footer: Callable[[], None] | None = None,
    box_title: str = "CREATIVE PREVIEW",
    box_subtitle: str = "Image generation added next",
    note: str = "",
) -> None:
    """A card for a concept whose finished ad does NOT exist (yet): a dashed
    box where the ad will appear, with a state title/subtitle (default
    "CREATIVE PREVIEW / Image generation added next"; Creative Lab V3 passes
    "AD NOT GENERATED YET", "GENERATING", or "GENERATION FAILED"), the
    concept's own strategic text, and an optional footer. Never calls an
    image provider and never substitutes a real asset.

    Reuses the same card/badge/CTA-pill/muted primitives as render_ad_preview
    rather than inventing a second visual language.

    `footer`, if given, is called last, still INSIDE this card's own
    bordered container (e.g. a checkbox or retry button): the base
    stylesheet's equal-height-row CSS pins a card's own last child to the
    bottom, so a control rendered here lines up across a row of unequal
    cards; the same control rendered AFTER this function returns (outside
    the card) would not.
    """
    with card("standard"):
        badge_row([angle_label.upper()])
        st.markdown(
            '<div style="border: 1px dashed rgba(127, 127, 127, 0.35); border-radius: 8px; '
            'padding: 1.4rem 1rem; text-align: center; margin-bottom: 0.6rem; opacity: 0.8;">'
            f'<div style="font-weight: 600; letter-spacing: 0.04em; font-size: 0.85rem;">{html.escape(box_title)}</div>'
            f'<div class="ui-quiet" style="margin-top: 0.2rem;">{html.escape(box_subtitle)}</div>'
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
        if note:
            muted(note)
        if why_this_exists:
            muted(why_this_exists)
        if footer:
            footer()


def render_creative_brief(*, angle_label: str, strategic_idea: str, why_this_exists: str) -> None:
    """A pre-generation "creative direction" card (Milestone 28.4, restored
    to the earlier card's proportions in 28.5): what Creative Studio
    proposes to explore for this concept, presented as a brief to review,
    never as a near-finished ad. Reuses the same tall "empty creative slot"
    shape and dashed placeholder box as the pre-Creative-Studio-V3 card
    (badge, then a dashed box where the eventual ad will appear, "AD NOT
    GENERATED YET" / "A finished ad will appear here"), which is what makes
    the pre- and post-generation states in the SAME grid position visually
    obvious as one becoming the other. The 28.4 correction remains: nothing
    below the box is ad copy. Only the concept's own two real strategic
    fields appear (`angle` as "Strategic idea", `why_this_concept_exists` as
    "Why we're exploring this") - no headline, no body copy, no CTA pill, no
    Include-in-experiment control (nothing exists yet to include).
    `wide_labels` forces each field to its own full-width row regardless of
    card width, since these are multi-sentence strategy statements, not
    short values meant to sit side by side.

    Sits in the same three-column row as render_generated_ad once a concept
    is generated, so it inherits the same equal-height-row CSS: reviewing
    three directions of uneven length still lines up as three even cards.

    Milestone 28.6: the base stylesheet's equal-height-row rule pins a
    card's own LAST element to the bottom (`margin-top: auto`) so a
    footer control (Retry/Regenerate/Include, in render_creative_placeholder
    and render_generated_ad) sits flush at the card's bottom across a row of
    uneven cards. This card has no footer, so its field_grid - the actual
    body content - WAS that last element, and got pushed down by whatever
    empty space the row's equal-height stretch left, instead of following
    the dashed box immediately: the shorter a concept's own angle/rationale
    text, the further down its content started. A trailing, invisible
    (display:none) marker div, always the true last DOM child, absorbs that
    rule instead: display:none removes it from the flex layout entirely, so
    :last-child matches it rather than field_grid, and field_grid flows
    top-down right after the dashed box in every card regardless of its own
    or its siblings' text length; only the leftover space at the card's
    bottom (below the content) still grows or shrinks, exactly as the equal-
    height row already intends.
    """
    with card("standard"):
        badge_row([angle_label.upper()])
        st.markdown(
            '<div style="border: 1px dashed rgba(127, 127, 127, 0.35); border-radius: 8px; '
            'padding: 1.4rem 1rem; text-align: center; margin-bottom: 0.6rem; opacity: 0.8;">'
            '<div style="font-weight: 600; letter-spacing: 0.04em; font-size: 0.85rem;">AD NOT GENERATED YET</div>'
            '<div class="ui-quiet" style="margin-top: 0.2rem;">A finished ad will appear here</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        field_grid(
            [("Strategic idea", strategic_idea), ("Why we're exploring this", why_this_exists)],
            wide_labels=("Strategic idea", "Why we're exploring this"),
        )
        st.markdown('<div style="display:none;"></div>', unsafe_allow_html=True)


def render_generated_ad(
    *,
    angle_label: str,
    image_path: str | None,
    primary_text: str,
    headline: str,
    description: str = "",
    cta: str = "",
    why_this_exists: str = "",
    footer: Callable[[], None] | None = None,
) -> None:
    """A FINISHED ad as one card: the generated image, then the structured
    Meta fields that live outside it (Primary text, Headline, Description,
    CTA), then the concept's quiet strategic rationale, then an optional
    footer (selection / regenerate controls). Used by BOTH Creative Lab and
    Experiments so the exact same ad reads identically in both places.

    Pure presentation of data the caller already has: never generates,
    rewrites or trims copy. A missing image file shows a plain "Creative
    unavailable" box, never a crash (core.assets.generated_asset_exists is
    checked at render time by callers, since a stored path is a snapshot).
    """
    from pathlib import Path

    with card("standard"):
        badge_row([angle_label.upper()])
        if image_path and Path(image_path).is_file():
            st.image(str(image_path), use_column_width=True)
        else:
            st.markdown(
                '<div style="border: 1px dashed rgba(127, 127, 127, 0.35); border-radius: 8px; padding: 1.4rem 1rem; '
                'text-align: center; margin-bottom: 0.6rem; opacity: 0.8;"><div style="font-weight: 600; '
                'letter-spacing: 0.04em; font-size: 0.85rem;">CREATIVE UNAVAILABLE</div></div>',
                unsafe_allow_html=True,
            )
        field_grid_items = [("Primary text", primary_text), ("Headline", headline)]
        if description:
            field_grid_items.append(("Description", description))
        for label, value in field_grid_items:
            st.markdown(
                f'<div class="ui-ad-field"><div class="ui-field-label">{html.escape(label)}</div>'
                f'<div class="ui-ad-field-value">{html.escape(value).replace("$", "&#36;")}</div></div>',
                unsafe_allow_html=True,
            )
        if cta:
            st.markdown(
                f'<div class="ui-ad-field"><div class="ui-field-label">CTA</div>'
                f'<span class="ui-ad-cta">{html.escape(cta)}</span></div>',
                unsafe_allow_html=True,
            )
        if why_this_exists:
            muted(why_this_exists)
        if footer:
            footer()


def _field_cells(items: list[tuple[str, str]], wide_labels: tuple[str, ...] = ()) -> str:
    cells = []
    for label, value in items:
        wide = " ui-field-wide" if label and label in wide_labels else ""
        label_html = f'<div class="ui-field-label">{html.escape(label)}</div>' if label else ""
        cells.append(f'<div class="ui-field{wide}">{label_html}<div class="ui-field-value">{html.escape(value)}</div></div>')
    return "".join(cells)


def field_grid(items: list[tuple[str, str]], wide_labels: tuple[str, ...] = (), quiet: bool = False) -> None:
    """A compact grid of (label, value) fields as ONE element: values wrap
    naturally, every value starts at the same top position directly under
    its own label (grid align-items:start, so a value that takes several
    lines never pushes a shorter neighbour down), and the grid reflows to
    fewer columns at narrow widths. Values are plain text (HTML-escaped),
    never markdown. A label in `wide_labels` spans the whole row. Replaces
    per-value st.columns + ui.muted + st.write, whose separate elements
    were spaced by Streamlit's own gap and bottom-aligned by the card CSS.
    """
    quiet_cls = " ui-field-quiet" if quiet else ""
    st.markdown(f'<div class="ui-fields{quiet_cls}">{_field_cells(items, wide_labels)}</div>', unsafe_allow_html=True)


def grouped_field_grid(groups: list[tuple[str, list[tuple[str, str]]]]) -> None:
    """field_grid with named groups: [(group title, [(label, value), ...])].
    Each group is a small uppercase title over its own top-aligned grid; a
    light rule separates consecutive groups, so related fields read as one
    unit and the groups read as distinct steps. A field with an empty label
    renders just its value (e.g. a one-line summary under its group title).
    One element, HTML-escaped plain text, same alignment guarantees as
    field_grid.
    """
    parts = []
    for title, items in groups:
        parts.append(
            f'<div class="ui-field-group"><div class="ui-field-group-title">{html.escape(title)}</div>'
            f'<div class="ui-fields">{_field_cells(items)}</div></div>'
        )
    st.markdown(f'<div class="ui-field-groups">{"".join(parts)}</div>', unsafe_allow_html=True)


def comparison_table(first_header: str, metric_headers: list[str], rows: list[dict]) -> None:
    """A responsive comparison table: each row is {"name", "note" (optional),
    "cells": [one string per metric header]}. The name column wraps; metric
    cells never break mid-value; at narrow widths the table scrolls
    horizontally inside its own container instead of overflowing the page
    or stacking into an unreadable column layout. All text is HTML-escaped.
    """
    head = "".join(f"<th>{html.escape(h)}</th>" for h in [first_header, *metric_headers])
    body = ""
    for row in rows:
        note = f'<div class="ui-quiet">{html.escape(row["note"])}</div>' if row.get("note") else ""
        cells = "".join(f'<td class="ui-num">{html.escape(c)}</td>' for c in row["cells"])
        body += f'<tr><td class="ui-table-main"><strong>{html.escape(row["name"])}</strong>{note}</td>{cells}</tr>'
    st.markdown(
        f'<div class="ui-table-wrap"><table class="ui-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


_SCROLL_REQUEST_KEY = "_ui_scroll_to_top_request"
_SCROLL_COUNTER_KEY = "_ui_scroll_to_top_counter"

# Streamlit's scrollable page container is <section class="main"> (confirmed
# against the installed 1.37 frontend bundle); components.html iframes are
# sandboxed with allow-same-origin, so window.parent.document is reachable.
# Three bounded attempts (now, next frame, shortly after), never a loop, to
# outlast Streamlit swapping stale elements for the new render.
_SCROLL_JS = """<script>/* scroll request __NONCE__ */
(function () {
  var doc;
  try { doc = window.parent.document; } catch (e) { return; }
  function go() {
    var el = doc.querySelector('section.main');
    if (el) { el.scrollTo(0, 0); }
    try { window.parent.scrollTo(0, 0); } catch (e) {}
  }
  go();
  window.requestAnimationFrame(go);
  window.setTimeout(go, 120);
})();
</script>"""


def request_scroll_to_top() -> None:
    """Ask for ONE scroll-to-top on the next render. Call from an on_click
    callback that moves the page to a different view (it runs before the
    rerender). Only sets a flag; nothing scrolls until the page calls
    apply_pending_scroll_to_top(), which consumes the flag, so an
    unrelated rerun (a checkbox, a tab, an expander) never scrolls.
    """
    counter = st.session_state.get(_SCROLL_COUNTER_KEY, 0) + 1
    st.session_state[_SCROLL_COUNTER_KEY] = counter
    st.session_state[_SCROLL_REQUEST_KEY] = counter


def apply_pending_scroll_to_top() -> None:
    """Call once, at the same fixed spot near the top of a page, on every
    run. Always reserves an st.empty() slot (display:none in Streamlit, so
    no visible gap) so the element positions after it, notably an st.tabs
    whose active tab Streamlit tracks by position, are identical whether or
    not a scroll is pending. When a request is pending it is popped (so it
    fires once) and a zero-height iframe is rendered into the slot. The
    request counter is embedded in the iframe's HTML so two consecutive
    requests never render byte-identical content, which Streamlit would
    otherwise treat as unchanged and not re-run.
    """
    slot = st.empty()
    request = st.session_state.pop(_SCROLL_REQUEST_KEY, None)
    if request is None:
        return
    with slot:
        components.html(_SCROLL_JS.replace("__NONCE__", str(request)), height=0)


def text_stack(primary: str, secondary: str | None = None, bold_primary: bool = False) -> None:
    """A primary line with an optional quieter supporting line directly
    beneath it, as ONE element, so the pair always keeps the same relative
    spacing however Streamlit spaces neighbouring elements (a st.write
    followed by a ui.muted was two elements with an uncontrolled gap).
    Plain text, HTML-escaped. Meant for use inside ui.card(rhythm=True).
    """
    def safe(text: str) -> str:
        # "$" as an entity so Streamlit's markdown never pairs two currency
        # values into a LaTeX span.
        return html.escape(text).replace("$", "&#36;")

    bold = " ui-stack-bold" if bold_primary else ""
    second = f'<div class="ui-stack-secondary">{safe(secondary)}</div>' if secondary else ""
    st.markdown(f'<div class="ui-stack-primary{bold}">{safe(primary)}</div>{second}', unsafe_allow_html=True)


def supporting_text(text: str) -> None:
    """A page-level supporting line under a title: readable (1rem, not a
    tiny caption), secondary (reduced opacity), with a deliberate section
    gap after it. Plain text, HTML-escaped.
    """
    st.markdown(f'<div class="ui-supporting">{html.escape(text)}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    """A small page-level or expander-level note that keeps normal spacing
    after it (unlike muted(), whose HTML block loses 1rem to Streamlit's
    markdown margin, leaving the next element flush against it). Plain
    text, HTML-escaped.
    """
    st.markdown(f'<div class="ui-note">{html.escape(text)}</div>', unsafe_allow_html=True)


def theme_label(theme: str) -> str:
    """The ONE display form of a customer theme name: sentence case ("Taste &
    odor", "Bottled water frustration"), matching how the theme is stored in
    customer_signals.csv. Display only: never used for matching, joins or
    ids. Exists because some pages previously title-cased the same theme
    ("Taste & Odor") while others showed it as stored.
    """
    text = theme.strip()
    return text[:1].upper() + text[1:].lower()


def callout(label: str, text: str, emphasis: bool = False) -> None:
    """A lightweight labeled callout: small uppercase label over one line or
    two of text, marked by a left accent rule instead of a box. `emphasis`
    enlarges and weights the text for the single most important sentence in
    a section. Plain text, HTML-escaped ($ as an entity).
    """
    strong = " ui-callout-strong" if emphasis else ""
    safe_label = html.escape(label).replace("$", "&#36;")
    safe_text = html.escape(text).replace("$", "&#36;")
    st.markdown(
        f'<div class="ui-callout-wrap"><div class="ui-callout{strong}"><div class="ui-callout-label">{safe_label}</div>'
        f'<div class="ui-callout-text">{safe_text}</div></div></div>',
        unsafe_allow_html=True,
    )


def numbered_badge(number: int, label: str) -> None:
    """An eyebrow line: a quiet ordinal (01) followed by a category badge,
    as one element. Plain text, HTML-escaped."""
    st.markdown(
        f'<div class="ui-badge-row ui-numbered-badge"><span class="ui-finding-number">{number:02d}</span>'
        f'<span class="ui-badge">{html.escape(label)}</span></div>',
        unsafe_allow_html=True,
    )


def titled_summary(title: str, summary: str, note_label: str | None = None, note: str | None = None) -> None:
    """An expanded intelligence-object body as ONE element: a strong title,
    a normal-weight summary, and an optional small-labeled secondary note
    (e.g. WHY IT MATTERS). Plain text, HTML-escaped ($ as an entity)."""
    def safe(t: str) -> str:
        return html.escape(t).replace("$", "&#36;")

    parts = [f'<div class="ui-titled-title">{safe(title)}</div>', f'<div class="ui-titled-summary">{safe(summary)}</div>']
    if note:
        if note_label:
            parts.append(f'<div class="ui-titled-note-label">{safe(note_label)}</div>')
        parts.append(f'<div class="ui-titled-note">{safe(note)}</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


def safe_paragraph(text: str) -> None:
    """A normal-weight paragraph of data-derived text (Milestone 29): the
    same visual weight as st.write on a plain string, but HTML-escaped
    ($ as an entity), so a sentence assembled from real values - a currency
    amount, a percentage, several such values in one sentence - never gets
    silently reinterpreted as Markdown/LaTeX by st.write's own markdown
    handling (Streamlit pairs two "$" into an inline math span, which is
    exactly what broke evidence summaries like "$6,403 spend; ... $5,102
    spend"). Use this instead of st.write/st.markdown for any string built
    from data rather than typed directly in this codebase; a literal string
    written directly here (no data values inside it) has nothing to escape
    and can keep using st.write.
    """
    st.markdown(f'<div class="ui-paragraph">{html.escape(text).replace("$", "&#36;")}</div>', unsafe_allow_html=True)


def render_evidence_item(label: str, detail: str, source: str, table=None) -> None:
    """One piece of supporting Evidence inside a "View evidence" expander
    (Milestone 29): a bold label, its detail, and its source, safely
    escaped for the same reason as safe_paragraph. When `detail` is a
    "; "-joined list of independent clauses (several qualifying styles'
    own metrics, already assembled that way by the caller - see
    agents/intelligence/engine.py's Performance Pattern evidence), it
    renders as a short bulleted list instead of one dense run-on sentence;
    a single clause renders exactly as before, one plain line. Purely a
    presentation choice: never re-derives, reorders, or rewords the
    evidence text itself, and the values are unchanged either way.
    """
    def safe(t: str) -> str:
        return html.escape(t).replace("$", "&#36;")

    clauses = [c.strip() for c in detail.split("; ") if c.strip()]
    if len(clauses) > 1:
        body = "<ul class=\"ui-evidence-list\">" + "".join(f"<li>{safe(c)}</li>" for c in clauses) + "</ul>"
    else:
        body = f'<div class="ui-evidence-detail">{safe(detail)}</div>'
    st.markdown(f'<div class="ui-evidence-label">{safe(label)}</div>{body}', unsafe_allow_html=True)
    st.caption(f"Source: {source}")
    if table is not None:
        st.dataframe(table, hide_index=True, use_container_width=True)


def insight_blocks(blocks: list[tuple[str, str]]) -> None:
    """A compact, labeled multi-part explanation (Milestone 29) - "What
    we're seeing" / "Evidence" / "Keep in mind" - for analysis that already
    separates into that many distinct, ALREADY-COMPUTED pieces (e.g. a
    Performance Agent's own learning_statement and limitations fields).
    Each block is exactly one of the caller's own existing strings, never
    re-derived, reworded, or split out of a single paragraph here; this
    replaces an unlabeled text_stack of the same two strings with labels
    that make the distinction between them explicit at a glance. One
    element, so spacing between blocks stays fixed regardless of text
    length. Reuses the same small-uppercase-label-over-text idiom as
    titled_summary's "WHY IT MATTERS" note. Plain text, HTML-escaped ($ as
    an entity). A block with empty/falsy text is skipped, so an optional
    piece never leaves a bare label on screen.
    """
    def safe(t: str) -> str:
        return html.escape(t).replace("$", "&#36;")

    parts = [
        f'<div class="ui-insight-block"><div class="ui-insight-label">{safe(label)}</div>'
        f'<div class="ui-insight-text">{safe(text)}</div></div>'
        for label, text in blocks
        if text
    ]
    if parts:
        st.markdown(f'<div class="ui-insight-blocks">{"".join(parts)}</div>', unsafe_allow_html=True)
