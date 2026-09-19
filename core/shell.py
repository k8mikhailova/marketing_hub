"""Shared Streamlit UI shell.

This is the single place that owns global app chrome: the sidebar, the client
selector, page navigation, and the client state that persists across pages.
Individual pages must not render their own client selector, app title, or
sidebar. They call into this module instead. When we add Ask Marketing Hub
or Agent Activity, they get wired in here once, and every page picks it up
automatically.
"""
import streamlit as st

from core.clients import default_client_id, get_active_clients, get_client

CLIENT_STATE_KEY = "client_id"


def render_sidebar(pages: list) -> None:
    """Render the sidebar: client/workspace context first, then navigation.

    `pages` are the same st.Page objects passed to st.navigation() in
    app.py (called with position="hidden" so its auto-drawn nav widget
    doesn't also appear). Rendering the links here, after the client
    selector, keeps "which workspace am I in" the first thing a marketer
    sees, with "where do I go" right below it.
    """
    st.sidebar.title("Softline Marketing Hub")

    active_clients = get_active_clients()
    client_ids = [c["client_id"] for c in active_clients]
    client_names = {c["client_id"]: c["name"] for c in active_clients}

    if CLIENT_STATE_KEY not in st.session_state:
        st.session_state[CLIENT_STATE_KEY] = default_client_id()

    st.sidebar.selectbox(
        "Client",
        options=client_ids,
        format_func=lambda cid: client_names[cid],
        key=CLIENT_STATE_KEY,
    )

    st.sidebar.divider()
    for page in pages:
        st.sidebar.page_link(page)


def current_client() -> dict:
    """The client dict for whatever is currently selected in session state."""
    client_id = st.session_state.get(CLIENT_STATE_KEY) or default_client_id()
    client = get_client(client_id)
    if client is None:
        raise ValueError(f"Unknown client_id in session state: {client_id}")
    return client


def render_placeholder_page(title: str, purpose: str) -> None:
    """Shared layout for a not-yet-built page: title, purpose, selected client."""
    client = current_client()

    st.title(title)
    st.caption(purpose)
    st.info(f"Selected client: **{client['name']}**")
    st.divider()
    st.markdown(
        "This page is a placeholder. Real (simulated) content replaces this "
        "message in a later milestone."
    )
