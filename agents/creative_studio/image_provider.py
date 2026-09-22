"""Image-generation provider abstraction for Creative Studio's live
generation step.

Kept deliberately separate from concept generation (agents/creative_studio/
engine.py) and from prompt construction (agents/creative_studio/
generation.py): this module answers only "render this prompt against this
reference image," nothing about what the experiment is or why. A provider
never reinterprets a concept, never invents copy, and never decides what to
change; it renders what generation.py's prompt already specifies.

One provider is implemented: OpenAIImageProvider. With a reference image it
uses OpenAI's image-editing API (images.edit); WITHOUT one (Milestone 27:
a concept is not forced to inherit a reference) it uses images.generate.
Both take only parameters present in the installed openai SDK's signatures.
The model id is NOT hardcoded here: it comes from agents/creative_studio/
config.py (override with OPENAI_IMAGE_MODEL), the single place a model is
named. The API returns image bytes as base64 (b64_json), not a URL, for GPT
image models, so this provider always decodes and returns raw bytes.

Adding a second provider (Google, FLUX, etc.) later means writing one more
class with the same generate_image(prompt, reference_image_path, ...)
signature; nothing in agents/creative_studio/generation.py or
app_pages/creative_lab.py would need to change.
"""
import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agents.creative_studio.config import DEFAULT_IMAGE_QUALITY, DEFAULT_IMAGE_SIZE, image_model

DEFAULT_SIZE = DEFAULT_IMAGE_SIZE
DEFAULT_QUALITY = DEFAULT_IMAGE_QUALITY


class ImageGenerationError(Exception):
    """Raised for any provider-side failure: missing/invalid API key, auth
    failure, timeout, refusal, or a malformed response. The message is
    always safe to show a user directly: it never includes the API key or
    raw provider response internals.
    """


@dataclass
class ProviderImageResult:
    """One rendered image and the facts needed to trace it back to the
    provider call that produced it. image_bytes is the raw file content;
    the caller (agents/creative_studio/generation.py) owns writing it to
    disk, so this module has no filesystem concerns at all.
    """

    image_bytes: bytes
    output_format: str
    provider: str
    model: str
    revised_prompt: str | None = None


class ImageGenerationProvider(Protocol):
    """The one interface every image provider implements. Deliberately a
    single method: render a prompt against a reference image. A provider
    never sees a CreativeConcept, an ExperimentProposal, or client context;
    it only ever sees the final prompt string generation.py already built.
    """

    def generate_image(
        self,
        prompt: str,
        reference_image_path: Path | None,
        *,
        size: str = DEFAULT_SIZE,
        quality: str = DEFAULT_QUALITY,
    ) -> ProviderImageResult: ...


def _safe_reason(exc: Exception) -> str:
    """A short, user-safe description of a provider exception: never the
    full exception repr, which for an HTTP client can include request
    headers or other internals a user should never see.
    """
    message = getattr(exc, "message", None) or str(exc)
    return message[:200]


class OpenAIImageProvider:
    """Reference-image-based generation via OpenAI's images.edit endpoint.

    Requires OPENAI_API_KEY in the environment; never reads a key from
    anywhere else (no hardcoded fallback, no config file), and never logs
    or echoes it. Raises ImageGenerationError, with a message safe to show
    directly to a user, for every failure mode: missing key, auth failure,
    timeout, refusal, or a malformed response.
    """

    PROVIDER_NAME = "openai"

    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ImageGenerationError(
                "Live creative generation requires OPENAI_API_KEY to be set in the environment. See README for "
                "setup, then try again."
            )
        # Imported here, not at module load, so importing this module never
        # requires the openai package to be importable in an environment
        # that only ever uses the deterministic concept-generation path.
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)

    def generate_image(
        self,
        prompt: str,
        reference_image_path: Path | None,
        *,
        size: str = DEFAULT_SIZE,
        quality: str = DEFAULT_QUALITY,
    ) -> ProviderImageResult:
        import openai as openai_sdk

        model = image_model()
        try:
            if reference_image_path is None:
                response = self._client.images.generate(model=model, prompt=prompt, size=size, quality=quality, n=1)
            else:
                if not Path(reference_image_path).exists():
                    raise ImageGenerationError("The reference image for this creative is no longer available.")
                with open(reference_image_path, "rb") as f:
                    response = self._client.images.edit(
                        model=model, image=f, prompt=prompt, size=size, quality=quality, n=1
                    )
        except openai_sdk.AuthenticationError:
            raise ImageGenerationError("OpenAI rejected the API key. Check OPENAI_API_KEY and try again.")
        except openai_sdk.APITimeoutError:
            raise ImageGenerationError("The image provider timed out. Try again in a moment.")
        except openai_sdk.BadRequestError as exc:
            raise ImageGenerationError(f"The image provider rejected this request: {_safe_reason(exc)}")
        except openai_sdk.APIError as exc:
            raise ImageGenerationError(f"The image provider returned an error: {_safe_reason(exc)}")

        if not response.data:
            raise ImageGenerationError("The image provider returned no image data.")
        item = response.data[0]
        if not item.b64_json:
            raise ImageGenerationError("The image provider response did not include image data in the expected format.")
        try:
            image_bytes = base64.b64decode(item.b64_json)
        except (ValueError, binascii.Error):
            raise ImageGenerationError("The image provider returned malformed image data.")

        return ProviderImageResult(
            image_bytes=image_bytes,
            output_format=response.output_format or "png",
            provider=self.PROVIDER_NAME,
            model=model,
            revised_prompt=getattr(item, "revised_prompt", None),
        )


def get_default_provider() -> ImageGenerationProvider:
    """The provider Creative Lab uses today. Raises ImageGenerationError
    immediately (before any network call) if OPENAI_API_KEY isn't set, so a
    caller can show a clear, human-readable message rather than a stack
    trace.
    """
    return OpenAIImageProvider()
