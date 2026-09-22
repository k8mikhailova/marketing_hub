"""The ONE place Creative Studio's model choices and generation defaults
live. Nothing else in the repository hardcodes an OpenAI model id: the image
provider, the text provider, the UI and the docs all read these functions, so
changing a model is one edit here (or one environment variable) and never a
search across files.

Both models are configurable at runtime through the environment (the same
.env convention OPENAI_API_KEY already uses), read at CALL time rather than
import time so a changed .env or a test override takes effect immediately.

The defaults below are the models named in the Milestone 27 brief and the
earlier Creative Studio milestone. They have NOT been verified against the
live API in this environment (no key is exercised by any automated test):
the installed openai SDK types its model arguments as plain strings, so any
id is accepted by the client, but whether an id exists for a given account is
only discoverable by a real call. Override with OPENAI_IMAGE_MODEL /
OPENAI_TEXT_MODEL if either default is not available to you.
"""
import os

DEFAULT_IMAGE_MODEL = "gpt-image-2.5-sunburst"
DEFAULT_TEXT_MODEL = "gpt-5.2"

DEFAULT_IMAGE_SIZE = "1024x1024"
DEFAULT_IMAGE_QUALITY = "auto"


def image_model() -> str:
    return os.environ.get("OPENAI_IMAGE_MODEL", "").strip() or DEFAULT_IMAGE_MODEL


def text_model() -> str:
    return os.environ.get("OPENAI_TEXT_MODEL", "").strip() or DEFAULT_TEXT_MODEL
