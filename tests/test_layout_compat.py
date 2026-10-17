"""Regression coverage for the layout-polish pass on the deployed public
demo (marketing-hub-public-demo): several of core/ui.py's custom CSS
selectors were written against Streamlit 1.37.1's DOM and silently stopped
matching anything once the deployed app resolved to Streamlit 1.66.0 - no
exception, just dead CSS, which neither an HTTP smoke test nor the
AppTest-based exception checks in test_card_rendering.py can catch (they
only see whether a script raised, not whether its injected CSS still
matches anything in the real DOM). These tests check the stylesheet
string directly for the specific selectors confirmed dead against the
1.66.0 frontend bundle, and exercise the sidebar's own rendering path.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.ui import _BASE_CSS

ROOT = Path(__file__).resolve().parent.parent

# Confirmed by grepping the installed streamlit package's static JS bundle:
# these are no longer real data-testid values (or, for button[kind=...], no
# longer a real forwarded HTML attribute) in Streamlit 1.66.0.
_DEAD_SELECTORS = [
    'data-testid="stVerticalBlockBorderWrapper"',
    'data-testid="element-container"',
    'data-testid="column"',
    "button[kind=",
]


def test_base_css_has_no_known_dead_selectors():
    for dead in _DEAD_SELECTORS:
        assert dead not in _BASE_CSS, f"_BASE_CSS still contains the dead selector {dead!r}"


def test_base_css_uses_current_testids():
    for live in ['data-testid="stColumn"', 'data-testid="stElementContainer"', 'data-testid="stBaseButton-primary"']:
        assert live in _BASE_CSS, f"_BASE_CSS is missing the current selector {live!r}"


def test_sidebar_renders_title_nav_and_about_expander():
    """The sidebar polish pass (core/shell.py): tight gap container, one
    sub-container per nav item, and the disclaimer moved into a bottom
    "About this demo" expander. Runs the real entry point, not a page in
    isolation, since the sidebar is only ever drawn from app.py."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception, f"app.py raised: {[e.value for e in at.exception]}"
    assert [t.value for t in at.sidebar.title] == ["Marketing Intelligence Hub"]
    assert [pl.label for pl in at.sidebar.page_link] == [
        "Overview",
        "Customer Signals",
        "Insights",
        "Creative Lab",
        "Experiments",
    ]
    assert "About this demo" in [e.label for e in at.sidebar.expander]
