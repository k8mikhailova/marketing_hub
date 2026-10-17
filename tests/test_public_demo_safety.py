"""Checks for the marketing-hub-original-demo branch: this branch keeps the
original Streamlit 1.37.1 styling and component structure untouched, and
adds only the minimum needed to deploy it publicly (title rename, a
sidebar disclaimer, pinned dependencies). These tests confirm that
addition didn't break anything, and confirm (independent of the pinned
CREATIVE_GENERATION_MODE default) that a public visitor has no code path
to a paid OpenAI call: run with the real page scripts, through Streamlit's
own AppTest harness, in an environment with no OPENAI_API_KEY set, same as
Streamlit Community Cloud by default.

Every page except overview.py is tested standalone
(AppTest.from_file("app_pages/<page>.py")), not through app.py's own
st.navigation + switch_page: Streamlit 1.37.1's AppTest silently returns
an empty main-area tree after switch_page() on this app's st.navigation
setup (confirmed directly - the "main" tree had exactly one element, the
injected stylesheet, nothing from the page itself, with no exception
raised to explain why), even though the real app works correctly in an
actual browser. That's a limitation of this Streamlit version's own test
harness for st.navigation, not a bug in the app; testing each page
standalone sidesteps it and lets these tests see the page's real content.
overview.py is the one exception: it calls st.page_link() directly
(every other page uses st.switch_page(), which needs no pre-registered
page), and st.page_link() raises if the target page was never registered
via st.navigation - so overview.py is tested through app.py as the one
page that needs the real navigation context.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

STANDALONE_PAGES = [
    "app_pages/signals.py",
    "app_pages/intelligence.py",
    "app_pages/creative_lab.py",
    "app_pages/experiments.py",
]


@pytest.fixture(autouse=True)
def no_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CREATIVE_GENERATION_MODE", raising=False)


def test_overview_runs_without_exception_through_app_navigation():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception, f"overview.py raised: {[e.value for e in at.exception]}"
    assert [t.value for t in at.title] == ["Marketing Intelligence Hub"]


@pytest.mark.parametrize("page", STANDALONE_PAGES)
def test_page_runs_without_exception_standalone(page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=30)
    at.run()
    assert not at.exception, f"{page} raised: {[e.value for e in at.exception]}"


def test_sidebar_renders_title_nav_and_disclaimer():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    assert [t.value for t in at.sidebar.title] == ["Marketing Intelligence Hub"]
    assert [pl.label for pl in at.sidebar.get("page_link")] == [
        "Overview",
        "Customer Signals",
        "Insights",
        "Creative Lab",
        "Experiments",
    ]
    captions = [c.value for c in at.sidebar.caption]
    assert any("simulated" in c and "Not affiliated with Brio Water" in c for c in captions)


def test_creative_generation_mode_defaults_to_demo_with_no_env():
    from agents.creative_studio.generation import (
        CREATIVE_GENERATION_MODE_DEMO,
        creative_generation_mode,
        creative_generation_ready,
    )
    import os

    assert "CREATIVE_GENERATION_MODE" not in os.environ
    assert "OPENAI_API_KEY" not in os.environ
    assert creative_generation_mode() == CREATIVE_GENERATION_MODE_DEMO
    assert creative_generation_ready() is True


def test_creative_lab_generate_never_constructs_an_openai_client(monkeypatch):
    """The actual code path a visitor's click runs: _process_pending_demo
    only ever calls demo_playback.resolve_playback_creative (disk reads of
    already-committed sidecar files). Patching openai.OpenAI to raise if
    constructed at all, then actually clicking "Generate creatives" on the
    real rendered page and running its callback, is the guarantee
    agents/creative_studio/demo_playback.py's own docstring claims -
    checked here by executing the real click, not by reading the source
    and assuming it holds."""
    import openai

    def _raise(*args, **kwargs):
        raise AssertionError("openai.OpenAI() must never be constructed in demo mode")

    monkeypatch.setattr(openai, "OpenAI", _raise)

    at = AppTest.from_file(str(ROOT / "app_pages/creative_lab.py"), default_timeout=30)
    at.run()
    assert not at.exception
    generate_buttons = [b for b in at.button if b.label == "Generate creatives"]
    assert generate_buttons, "no 'Generate creatives' button found - page may not be rendering real content"
    generate_buttons[0].click().run(timeout=30)
    assert not at.exception, f"raised: {[e.value for e in at.exception]}"
    # Also confirms generation actually completed (not just "didn't crash"):
    # a real finished creative replaces the pre-generation brief, so the
    # checkbox this demo path renders only on a filled slot must now exist.
    assert any(cb.label == "Include in experiment" for cb in at.checkbox)


def test_reset_demo_button_runs_without_exception():
    at = AppTest.from_file(str(ROOT / "app_pages/creative_lab.py"), default_timeout=30)
    at.run()
    reset_buttons = [b for b in at.button if b.label == "Reset demo"]
    assert reset_buttons, "no 'Reset demo' button found"
    reset_buttons[0].click().run(timeout=30)
    assert not at.exception, f"raised: {[e.value for e in at.exception]}"
