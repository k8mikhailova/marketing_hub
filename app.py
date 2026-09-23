"""Softline Marketing Hub: Streamlit entry point.

This file owns global app chrome (page config + sidebar) and declares
navigation. All shared behavior lives in core/shell.py so there is exactly
one place to change it. Page files under app_pages/ only render their own
content and must not duplicate sidebar/client-selector logic.

Note: the folder is named app_pages/, not pages/. Streamlit auto-detects a
literal pages/ directory and builds its own navigation from it, which
conflicts with the explicit st.navigation() below.

st.navigation's own nav widget is rendered with position="hidden": the
sidebar's page links are instead drawn manually in core/shell.py, after the
client selector, so the client/workspace context always appears before
navigation. Routing is unaffected by this; only the widget's placement is.
st.navigation(...) is called before render_sidebar (Milestone 29) purely to
read pg.title, the current page's own name, so render_sidebar can render
that ONE entry with an explicit "you are here" treatment instead of relying
on Streamlit's own active-link styling; pg.run() (the part that actually
executes the current page's script) still happens last, so routing itself
is unaffected by the reorder.

Milestone 29.2: ui.inject_base_styles() is called here too, before
render_sidebar, in addition to each page's own call (kept for now; the CSS
is idempotent, so the duplicate is harmless - see core/ui.py's own
docstring). Streamlit tags every element with the identity of whichever
script was actually running when it was created; elements created here, in
app.py itself (the app's single "main script"), keep that identity across
every page navigation, while elements created inside a page module (each
call to inject_base_styles() living at the top of app_pages/*.py) are
tagged with THAT page's own identity and are dropped the moment a different
page becomes current. Since the shared stylesheet also carries the sidebar
nav-link and active-marker CSS, having it live ONLY inside each page meant
the sidebar's own elements - which, being created here in app.py, DO
persist across a page change - would briefly render unstyled (and the main
content area would briefly snap to Streamlit's own default width/padding)
in the gap between the old page's stylesheet disappearing and the new
page's own call re-adding it. Injecting it here first closes that gap: the
stylesheet now belongs to app.py itself, so it never leaves the tree at
all, precisely like the sidebar elements it styles.

load_dotenv() runs once here, before any page: it reads .env (gitignored,
never committed; see .env.example) into the process environment if present,
so OPENAI_API_KEY reaches agents/creative_studio/image_provider.py without
requiring a manual `export` in the shell. A missing .env file is not an
error: load_dotenv() is a no-op then, and image_provider.py's own
os.environ.get("OPENAI_API_KEY") check handles an unset key gracefully.
"""
import streamlit as st
from dotenv import load_dotenv

from core import ui
from core.shell import render_sidebar

load_dotenv()

st.set_page_config(
    page_title="Softline Marketing Hub",
    page_icon="📊",
    layout="wide",
)

pages = [
    st.Page("app_pages/overview.py", title="Overview"),
    st.Page("app_pages/signals.py", title="Customer Signals"),
    st.Page("app_pages/intelligence.py", title="Insights"),
    st.Page("app_pages/creative_lab.py", title="Creative Lab"),
    st.Page("app_pages/experiments.py", title="Experiments"),
]

pg = st.navigation(pages, position="hidden")
ui.inject_base_styles()
render_sidebar(pages, current_title=pg.title)
pg.run()
