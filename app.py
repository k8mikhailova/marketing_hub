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

load_dotenv() runs once here, before any page: it reads .env (gitignored,
never committed; see .env.example) into the process environment if present,
so OPENAI_API_KEY reaches agents/creative_studio/image_provider.py without
requiring a manual `export` in the shell. A missing .env file is not an
error: load_dotenv() is a no-op then, and image_provider.py's own
os.environ.get("OPENAI_API_KEY") check handles an unset key gracefully.
"""
import streamlit as st
from dotenv import load_dotenv

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

render_sidebar(pages)

pg = st.navigation(pages, position="hidden")
pg.run()
