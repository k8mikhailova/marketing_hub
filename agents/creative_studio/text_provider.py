"""OpenAI implementation of execution.TextGenerationProvider: turns the
structured strategy context into candidate ad copy as a validated structured
object. Kept in its own module so nothing in Creative Lab imports OpenAI
directly (mirrors image_provider.py), and so importing the rest of Creative
Studio never requires the openai package.

Uses chat.completions.parse with a pydantic response_format (the SDK's
structured-output path, present in the installed openai package). The model
id comes from agents/creative_studio/config.py (override: OPENAI_TEXT_MODEL),
never a literal here. No temperature or other sampling parameter is passed:
not every model accepts them, and determinism is not claimed for this step.

Requires OPENAI_API_KEY from the environment; never reads a key anywhere
else and never logs or echoes it. Every failure becomes a TextGenerationError
whose message is safe to show a user.
"""
import os

from agents.creative_studio.config import text_model
from agents.creative_studio.execution import ExecutionCopy, TextGenerationError
from agents.creative_studio.image_provider import _safe_reason


class OpenAITextProvider:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise TextGenerationError(
                "Live creative generation requires OPENAI_API_KEY to be set in the environment. See README for "
                "setup, then try again."
            )
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = text_model()

    def generate_execution_copy(self, system: str, user: str) -> dict:
        import openai as openai_sdk

        try:
            response = self._client.chat.completions.parse(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=ExecutionCopy,
            )
        except openai_sdk.AuthenticationError:
            raise TextGenerationError("OpenAI rejected the API key. Check OPENAI_API_KEY and try again.")
        except openai_sdk.APITimeoutError:
            raise TextGenerationError("The copy generator timed out. Try again in a moment.")
        except openai_sdk.BadRequestError as exc:
            raise TextGenerationError(f"The copy generator rejected this request: {_safe_reason(exc)}")
        except openai_sdk.APIError as exc:
            raise TextGenerationError(f"The copy generator returned an error: {_safe_reason(exc)}")

        if not response.choices:
            raise TextGenerationError("The copy generator returned no result.")
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise TextGenerationError("The copy generator declined this request. Try again or adjust the strategy.")
        parsed = message.parsed
        if parsed is None:
            raise TextGenerationError("The copy generator returned a result that could not be parsed.")
        return parsed.model_dump()


def get_text_provider() -> OpenAITextProvider:
    """The text provider Creative Lab uses. Raises TextGenerationError
    immediately (before any network call) if OPENAI_API_KEY is not set."""
    return OpenAITextProvider()
