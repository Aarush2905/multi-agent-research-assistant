"""Google Gemini API client with structured JSON output enforcement and retries."""

from __future__ import annotations

import logging
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: genai.Client | None = None


class GeminiAuthError(Exception):
    """Raised when the configured Gemini API key is invalid or rejected."""


class GeminiGenerationError(Exception):
    """Raised when Gemini fails to produce valid output after retries."""


def _is_retryable(exc: BaseException) -> bool:
    """Retry on malformed outputs or transient 5xx / 429 server errors."""
    if isinstance(exc, (ValidationError, ValueError)):
        return True
    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.ClientError) and getattr(exc, "code", None) == 429:
        return True
    return False


def _log_before_sleep(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    delay = retry_state.next_action.sleep if retry_state.next_action else 0
    logger.warning(
        "Gemini request failed (attempt %d), retrying in %.1fs: %s",
        retry_state.attempt_number,
        delay,
        exc,
    )


def get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms),
        )
    return _client


async def test_auth() -> tuple[bool, str]:
    """Test if the configured GEMINI_API_KEY works. Returns (ok, message)."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return False, "GEMINI_API_KEY is not set. Add it to your .env file."
    try:
        client = get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents="Reply with exactly one word: OK",
            config=types.GenerateContentConfig(max_output_tokens=10, temperature=0),
        )
        text = (response.text or "").strip()
        if not text:
            return False, "Gemini responded but returned an empty completion."
        return True, f"Gemini auth OK (model={settings.gemini_model})."
    except Exception as exc:
        msg = str(exc)
        lower = msg.lower()
        if any(k in lower for k in ("api key", "unauthenticated", "permission", "401", "403")):
            return False, "Gemini authentication failed. Please verify GEMINI_API_KEY in .env."
        return False, f"Could not reach Gemini: {msg}"


def _get_retry_decorator():
    settings = get_settings()
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.gemini_max_retries),
        wait=wait_exponential(
            multiplier=1,
            min=settings.gemini_retry_min_wait_seconds,
            max=settings.gemini_retry_max_wait_seconds,
        ),
        retry=retry_if_exception(_is_retryable),
        before_sleep=_log_before_sleep,
    )


def generate_structured(
    prompt: str,
    response_model: type[T],
    *,
    system_instruction: str | None = None,
    temperature: float = 0.2,
) -> T:
    """Generate structured output validated against a Pydantic model with retry logic."""
    settings = get_settings()
    client = get_client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_model,
        temperature=temperature,
        system_instruction=system_instruction,
    )

    def _call():
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=prompt, config=config
            )
        except Exception as exc:
            msg = str(exc)
            if any(k in msg.lower() for k in ("api key", "unauthenticated", "permission", "401", "403")):
                raise GeminiAuthError("Gemini authentication failed - check GEMINI_API_KEY in .env") from exc
            raise

        raw_text = response.text
        if not raw_text:
            raise ValueError("Gemini returned an empty response body")
        return response_model.model_validate_json(raw_text)

    retryer = _get_retry_decorator()
    try:
        return retryer(_call)()
    except GeminiAuthError:
        raise
    except Exception as exc:
        raise GeminiGenerationError(
            f"Failed to produce valid structured output for {response_model.__name__}: {exc}"
        ) from exc


def generate_text(
    prompt: str,
    *,
    system_instruction: str | None = None,
    temperature: float = 0.3,
) -> str:
    """Generate free-form text response from Gemini."""
    settings = get_settings()
    client = get_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=system_instruction,
    )
    try:
        response = client.models.generate_content(
            model=settings.gemini_model, contents=prompt, config=config
        )
        return (response.text or "").strip()
    except Exception as exc:
        raise GeminiGenerationError(f"Gemini text generation failed: {exc}") from exc
