"""Shared Gemini model construction with HTTP retry enabled.

google-genai's own default (used whenever `Gemini.retry_options` is left
unset) collapses to zero retries — a single 5xx from Gemini
("This model is currently experiencing high demand") raises immediately and
kills the whole crew run (see google.genai._api_client.retry_args: a `None`
options value returns `tenacity.stop_after_attempt(1)`). Every LlmAgent in
this crew should ride out that kind of transient overload instead of
surfacing it as a hard pipeline error, so agent builders should construct
their model via `build_model()` rather than passing a bare model-name string.
"""

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
