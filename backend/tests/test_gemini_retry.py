from google.genai import errors as genai_errors
from pydantic import BaseModel, ValidationError

from app.gemini import _is_retryable


class _Dummy(BaseModel):
    x: int


def _validation_error() -> ValidationError:
    try:
        _Dummy.model_validate({"x": "not-an-int-but-this-string-also-fails"})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def test_retries_on_server_error_503():
    exc = genai_errors.ServerError(503, {"message": "high demand"}, None)
    assert _is_retryable(exc) is True


def test_retries_on_rate_limit_429():
    exc = genai_errors.ClientError(429, {"message": "rate limited"}, None)
    assert _is_retryable(exc) is True


def test_does_not_retry_on_other_client_errors():
    exc = genai_errors.ClientError(404, {"message": "model not found"}, None)
    assert _is_retryable(exc) is False


def test_does_not_retry_on_auth_client_error():
    exc = genai_errors.ClientError(403, {"message": "permission denied"}, None)
    assert _is_retryable(exc) is False


def test_retries_on_malformed_structured_output():
    assert _is_retryable(_validation_error()) is True
    assert _is_retryable(ValueError("empty response")) is True


def test_does_not_retry_on_unrelated_exception():
    assert _is_retryable(RuntimeError("unrelated")) is False
