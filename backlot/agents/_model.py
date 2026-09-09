"""Shared Gemini model construction with HTTP retry enabled."""

from __future__ import annotations

from google.adk.models import Gemini
from google.genai import types

_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=5,
    initial_delay=1.0,
    max_delay=20.0,
    exp_base=2.0,
)


def build_model(model_name: str) -> Gemini:
    return Gemini(model=model_name, retry_options=_RETRY_OPTIONS)
