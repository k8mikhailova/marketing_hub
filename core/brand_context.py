"""Lightweight client brand/creative context for image-generation prompts.

Reads clients/<client_id>/{brand_guidelines,products,profile}.md and
returns a short, prompt-ready string, never a whole markdown file's worth of
text: a live model prompt should get only what's genuinely useful, not
everything on file about a client.

Every client file in this demo currently carries only placeholder
boilerplate ("_Placeholder. To be filled in from real Brio ... materials
before this client's data is built out further."). That boilerplate is a
note to whoever edits the file, not real brand context, so it is filtered
out here rather than fed to a model as if it were genuine guidance.
creative_context() returns "" for a client with nothing but placeholders,
which is the honest answer right now, not a bug.
"""
from pathlib import Path

CLIENTS_DIR = Path(__file__).resolve().parent.parent / "clients"

PLACEHOLDER_MARKER = "_Placeholder."

# Read in this order: brand voice first, then product specifics, then
# general company profile, since a prompt has limited room and brand voice
# is the most likely to actually change what a generated creative looks like.
CONTEXT_FILES = ["brand_guidelines.md", "products.md", "profile.md"]


def _read_client_file(client_id: str, filename: str) -> str:
    path = CLIENTS_DIR / client_id / filename
    if not path.exists():
        return ""
    return path.read_text().strip()


def creative_context(client_id: str, max_chars: int = 600) -> str:
    """A short, prompt-ready brand context string for this client, or "" if
    only placeholder content exists. Truncated to max_chars so a future,
    filled-in client file can't balloon into an oversized prompt.
    """
    parts = [
        text
        for filename in CONTEXT_FILES
        if (text := _read_client_file(client_id, filename)) and PLACEHOLDER_MARKER not in text
    ]
    return "\n\n".join(parts).strip()[:max_chars]
