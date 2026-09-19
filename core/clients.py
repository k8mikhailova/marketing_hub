"""Client-registry helpers.

Deliberately has no Streamlit dependency: this module only knows how to read
clients/registry.json. UI concerns (sidebar, session state) live in
core/shell.py. Keeping the split means the registry logic stays testable and
reusable outside of a running Streamlit app.
"""
import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "clients" / "registry.json"


def load_registry() -> list[dict]:
    """Return every client entry, active or not."""
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


def get_active_clients() -> list[dict]:
    """Return only the clients that should be selectable in the app today."""
    return [c for c in load_registry() if c.get("active")]


def get_client(client_id: str) -> dict | None:
    """Look up a single client entry by id, active or not."""
    for c in load_registry():
        if c["client_id"] == client_id:
            return c
    return None


def default_client_id() -> str:
    """The client selected on first load, before the user picks one."""
    active = get_active_clients()
    if not active:
        raise ValueError("clients/registry.json has no active clients.")
    return active[0]["client_id"]
