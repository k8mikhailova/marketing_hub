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


def render_sidebar(pages: list, current_title: str | None = None) -> None:
    """Render the sidebar: client/workspace context first, then navigation.

    `pages` are the same st.Page objects passed to st.navigation() in
    app.py (called with position="hidden" so its auto-drawn nav widget
    doesn't also appear). Rendering the links here, after the client
    selector, keeps "which workspace am I in" the first thing a marketer
    sees, with "where do I go" right below it.

    `current_title` (Milestone 29, revised 29.1), if given, is the title of
    the page st.navigation already resolved for this run (app.py passes
    st.navigation(...).title before calling .run()). EVERY page, including
    the current one, renders as a real st.sidebar.page_link - Streamlit's
    own "is this the active page" signal (isCurrentPage) is a React prop
    consumed only by inline style computation and a boldLabel flag inside
    StreamlitMarkdown; confirmed against Streamlit 1.37.1's own source
    (PageLink.tsx / styled-components.ts) that it never reaches the DOM as
    an attribute, class, or aria-marker, so there is nothing for an
    external stylesheet to select. 29's first attempt swapped the current
    page for a hand-styled non-link <div> instead, matched to page_link's
    box by hand - but a div rendered via st.markdown sits in a
    stMarkdownContainer, which (see core/ui.py's own documented "ROOT CAUSE
    of uneven card spacing") carries Streamlit's own -1rem bottom-margin
    compensation for an assumed inner <p>; stPageLink containers carry no
    such compensation. That mismatch, present on whichever ONE item
    happened to be the div, is what made spacing look inconsistent
    depending on which page was current - a worse version of the original
    complaint, not a fix.

    The actual mechanism here: an invisible marker element (the same
    zero-size, :has()-keyed technique core/ui.py's rhythm CSS already uses)
    is rendered immediately before the current page's own page_link. CSS
    matches that marker's element-container and styles the very next
    element-container's real [data-testid="stPageLink-NavLink"] - so the
    current page's nav item is the exact same component, in the exact same
    per-item DOM wrapper, as the other four; only color/background/
    font-weight ever differ, never anything that affects box size.

    Milestone 29.2: a marker now precedes EVERY page's link, not only the
    current one - only its class ("...-current-marker" vs "...-marker")
    differs. Streamlit's own page-navigation reconciliation (traced through
    Streamlit 1.37.1's own source, AppNode.ts/AppNavigation.ts) preserves
    elements created here in app.py (this module's own caller) across a
    page change, since they carry the app's constant main-script identity
    rather than whichever page is newly current - but WHICH element is "the
    marker" used to shift position (it sat immediately before a different
    link on each page), so the sidebar's own element sequence had a
    different shape run to run, which is exactly the kind of change that
    forces a positional re-render of everything after the shift instead of
    an in-place patch. A fixed one-marker-per-link slot keeps that sequence
    identical - same element count, same types, same order - on every page;
    both marker classes are equally invisible (zero-size, :has()-hidden in
    core/ui.py), so this changes nothing about spacing, only which single
    marker's class flips the CSS selector below it.
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
        is_current = current_title is not None and page.title == current_title
        marker_class = "ui-sidebar-current-marker" if is_current else "ui-sidebar-marker"
        st.sidebar.markdown(f'<div class="{marker_class}"></div>', unsafe_allow_html=True)
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
