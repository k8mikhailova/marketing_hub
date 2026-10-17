"""Regression coverage for the StreamlitInvalidHeightError found on the
deployed public demo (marketing-hub-public-demo): core.ui.card() used to
pass height=None straight through to st.container, which newer Streamlit
(1.4x+) rejects outright. An HTTP-level smoke test (curl against a running
`streamlit run`) returns 200 even when a page throws this, because
Streamlit renders the exception as a normal part of the page instead of
failing the HTTP request - so these tests instead run the actual page
scripts and card-rendering code through Streamlit's own AppTest harness,
which surfaces any exception a script raised while running.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

PAGES = [
    "app_pages/overview.py",
    "app_pages/signals.py",
    "app_pages/intelligence.py",
    "app_pages/creative_lab.py",
    "app_pages/experiments.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_exception(page):
    """Starts from app.py (the real entry point) and switches to the target
    page, exactly like a visitor navigating the deployed app: st.navigation
    registers every page here first, which app_pages/overview.py's own
    st.page_link("app_pages/intelligence.py", ...) needs to resolve.
    Running a page file directly with AppTest.from_file skips that
    registration and fails on the page_link call alone, before ever
    reaching the card-rendering code this test exists to check."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    if page != PAGES[0]:
        at.switch_page(page)
        at.run()
    assert not at.exception, f"{page} raised: {[e.value for e in at.exception]}"


def _render_card(level, height=None, rhythm=False, soft=False):
    """AppTest.from_function re-executes this function's SOURCE in an
    isolated module, so it cannot close over pytest's parametrize values -
    every variant must be an actual argument, passed via kwargs=."""
    import streamlit as st

    from core import ui

    with ui.card(level, height=height, rhythm=rhythm, soft=soft):
        st.write("content")


@pytest.mark.parametrize("level", ["primary", "standard", "quiet"])
def test_card_default_height_does_not_raise(level):
    """The exact bug: card(level) with no height arg used to call
    st.container(height=None), which StreamlitInvalidHeightError rejects."""
    at = AppTest.from_function(_render_card, kwargs={"level": level})
    at.run()
    assert not at.exception, f"card({level!r}) raised: {[e.value for e in at.exception]}"


@pytest.mark.parametrize("level", ["primary", "standard", "quiet"])
def test_card_explicit_height_still_works(level):
    """Fixed heights (e.g. aligned rows of findings) must keep working."""
    at = AppTest.from_function(_render_card, kwargs={"level": level, "height": 200})
    at.run()
    assert not at.exception, f"card({level!r}, height=200) raised: {[e.value for e in at.exception]}"


@pytest.mark.parametrize("rhythm", [False, True])
@pytest.mark.parametrize("soft", [False, True])
def test_card_rhythm_and_soft_variants_do_not_raise(rhythm, soft):
    at = AppTest.from_function(
        _render_card, kwargs={"level": "standard", "rhythm": rhythm, "soft": soft}
    )
    at.run()
    assert not at.exception, f"card(rhythm={rhythm}, soft={soft}) raised: {[e.value for e in at.exception]}"
