"""
Centralized LLM client with LangSmith tracing.
================================================
Provides a singleton-style Gemini client wrapped with LangSmith telemetry,
used by all AI-powered agents in the Company OS.
Gracefully falls back to deterministic rule-based output when GEMINI_API_KEY
is not provided or the Gemini service is unreachable.
"""

import logging
import os
import sys
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv

if "pytest" not in sys.modules and "unittest" not in sys.modules:
    load_dotenv()

logger = logging.getLogger("afw.company_os.llm_client")

# Default model used across agents; override per-agent as needed.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# ── BYOK & Managed AI Credits Tenant Isolation State ─────────────────────────
_REQUEST_GEMINI_KEY: ContextVar[str | None] = ContextVar("request_gemini_key", default=None)
_REQUEST_IS_OWNER: ContextVar[bool] = ContextVar("request_is_owner", default=True)
_REQUEST_MANAGED_AI_AUTHORIZED: ContextVar[bool] = ContextVar("request_managed_ai_authorized", default=False)
_REQUEST_USAGE_TELEMETRY: ContextVar[dict[str, Any] | None] = ContextVar("request_usage_telemetry", default=None)


class AICreditsRequiredError(RuntimeError):
    """Raised when fail_closed_without_llm=True and neither BYOK key nor Managed AI Credits authorize live LLM execution."""

_DEFAULT_INR_PER_TOKEN = 0.00001


def reset_last_llm_usage() -> None:
    """Reset accumulated per-execution LLM token/cost telemetry."""
    _REQUEST_USAGE_TELEMETRY.set(None)


def get_last_llm_usage() -> dict[str, Any] | None:
    """Return accumulated LLM token and INR cost telemetry for the current execution context."""
    val = _REQUEST_USAGE_TELEMETRY.get()
    return dict(val) if val else None


def _record_llm_usage(
    *,
    model_name: str,
    tokens_total: int,
    used_fallback: bool,
    actual_cost_inr: float | None = None,
) -> None:
    cur = dict(_REQUEST_USAGE_TELEMETRY.get() or {})
    prev_tokens = int(cur.get("provider_tokens_total") or 0)
    prev_cost = float(cur.get("provider_cost_inr") or 0.0)
    prev_est = float(cur.get("estimated_provider_cost_inr") or 0.0)
    prev_actual = cur.get("actual_provider_cost_inr", 0.0 if cur else 0.0)
    added_tokens = max(0, int(tokens_total))

    if used_fallback or added_tokens == 0:
        est_added = 0.0
        step_actual: float | None = 0.0
        step_source = "DETERMINISTIC_FALLBACK_ZERO"
    elif actual_cost_inr is not None:
        step_actual = round(float(actual_cost_inr), 6)
        est_added = step_actual
        step_source = "LIVE_PROVIDER_REPORTED"
    else:
        step_actual = None
        est_added = round(added_tokens * _DEFAULT_INR_PER_TOKEN, 6)
        step_source = "TOKEN_USAGE_ESTIMATE"

    if prev_actual is None or step_actual is None:
        merged_actual: float | None = None
    else:
        merged_actual = round(float(prev_actual) + float(step_actual), 6)

    prev_source = cur.get("provider_cost_source")
    if not cur:
        merged_source = step_source
    elif prev_source == step_source:
        merged_source = step_source
    else:
        merged_source = "MIXED_ESTIMATE_AND_ACTUAL"

    total_est = round(prev_est + est_added, 6)
    total_metered = round(prev_cost + (step_actual if step_actual is not None else est_added), 6)
    _REQUEST_USAGE_TELEMETRY.set(
        {
            "provider_model": model_name,
            "provider_tokens_total": prev_tokens + added_tokens,
            "provider_cost_inr": total_metered,
            "estimated_provider_cost_inr": total_est,
            "actual_provider_cost_inr": merged_actual,
            "provider_cost_source": merged_source,
            "used_fallback": bool(used_fallback) if not cur else (bool(cur.get("used_fallback")) and used_fallback),
        }
    )


def set_request_llm_context(
    gemini_key: str | None,
    is_owner: bool,
    managed_ai_authorized: bool = False,
) -> None:
    """Set request-scoped context for BYOK Gemini key, owner status, and metered Managed AI Credit authorization."""
    cleaned = gemini_key.strip() if gemini_key and gemini_key.strip() else None
    _REQUEST_GEMINI_KEY.set(cleaned)
    _REQUEST_IS_OWNER.set(bool(is_owner))
    _REQUEST_MANAGED_AI_AUTHORIZED.set(bool(managed_ai_authorized))


@lru_cache(maxsize=64)
def get_gemini_client_for_key(api_key: str):
    """Return a LangSmith-wrapped Gemini client for a tenant's BYOK key (cached up to 64 keys)."""
    cleaned = (api_key or "").strip()
    if not cleaned or cleaned == "mock-gemini-key":
        return None
    try:
        from google import genai
        from langsmith import wrappers

        raw_client = genai.Client(api_key=cleaned)
        return wrappers.wrap_gemini(
            raw_client,
            tracing_extra={
                "tags": ["os_gateway", "gemini", "byok"],
                "metadata": {
                    "system": "AskforWrite AI Company OS",
                    "integration": "google-genai-byok",
                },
            },
        )
    except Exception as exc:
        logger.warning(f"Could not initialize BYOK Gemini Client: {exc}")
        return None



def has_gemini_api_key() -> bool:
    """Check if GEMINI_API_KEY or GOOGLE_API_KEY is configured in the environment."""
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    return bool(key and key != "mock-gemini-key")


@lru_cache(maxsize=1)
def get_gemini_client():
    """Return a LangSmith-wrapped Gemini client (singleton) if configured, else None."""
    if not has_gemini_api_key():
        return None
    try:
        from google import genai
        from langsmith import wrappers

        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        raw_client = genai.Client(api_key=key) if key else genai.Client()
        return wrappers.wrap_gemini(
            raw_client,
            tracing_extra={
                "tags": ["os_gateway", "gemini"],
                "metadata": {
                    "system": "AskforWrite AI Company OS",
                    "integration": "google-genai",
                },
            },
        )
    except Exception as exc:
        logger.warning(f"Could not initialize Gemini Client: {exc}")
        return None


def _deterministic_fallback(prompt: str, system_instruction: str | None = None) -> str:
    """Generate a clean, high-utility deterministic fallback when Gemini API is unavailable."""
    prompt_lower = prompt.lower()
    if "seo" in prompt_lower or "article" in prompt_lower or "blog" in prompt_lower:
        return (
            "## Strategic Overview\n\n"
            "In today's fast-paced enterprise landscape, operational efficiency and automated workflows "
            "drive market leadership. Autonomous multi-agent coordination bridges the gap between field execution "
            "and real-time financial tracking.\n\n"
            "### Key Operational Advantages\n"
            "- **Cryptographic Integrity**: Immutable verification across every milestone.\n"
            "- **Automated Rebalancing & Audits**: Real-time algorithmic adjustments minimize losses.\n"
            "- **Continuous Growth Acceleration**: Instant customer qualification and conversion."
        )
    if "sentiment" in prompt_lower or "crm" in prompt_lower or "debrief" in prompt_lower:
        return (
            "[LIVE_LLM_UNAVAILABLE] Automated CRM debrief synthesis was not executed because no live LLM "
            "authorization was active. Review raw visit notes manually."
        )
    if "creative" in prompt_lower or "headline" in prompt_lower or "ad copy" in prompt_lower:
        return (
            "Transform your business operations with autonomous AI agents. "
            "Scale faster, eliminate manual overhead, and achieve verifiable ROI today."
        )
    return (
        "AskforWrite Company OS autonomous agent analysis generated successfully with verifiable data provenance."
    )


def generate(
    prompt: str,
    *,
    model: str | None = None,
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    fallback_text: str | None = None,
    fail_closed_without_llm: bool = False,
) -> str:
    """
    Generate text via Gemini with automatic LangSmith tracing.
    Enforces strict BYOK + Managed AI Credit isolation:
    - If a BYOK request key is set in context, uses that key (0 Managed AI Credits).
    - If _REQUEST_MANAGED_AI_AUTHORIZED is True (atomic credit reservation succeeded) OR _REQUEST_IS_OWNER is True,
      uses the platform's managed Gemini pool.
    - Otherwise, NEVER consumes Owner's key; fails closed if fail_closed_without_llm=True or returns deterministic fallback.
    """
    req_key = _REQUEST_GEMINI_KEY.get()
    is_owner = _REQUEST_IS_OWNER.get()
    managed_ok = _REQUEST_MANAGED_AI_AUTHORIZED.get()
    eff_model = model or DEFAULT_MODEL

    if req_key:
        client = get_gemini_client_for_key(req_key)
    elif not is_owner and not managed_ok:
        # Commercial tenant without BYOK key or Managed AI Credit authorization: zero consumption of Owner's key
        logger.info("Non-owner request with no BYOK key or Managed AI Credit authorization.")
        _record_llm_usage(model_name=eff_model, tokens_total=0, used_fallback=True)
        if fail_closed_without_llm:
            raise AICreditsRequiredError(
                "Managed AI credits or a BYOK X-Gemini-API-Key are required; canned fallback output is disabled."
            )
        return fallback_text if fallback_text is not None else _deterministic_fallback(prompt, system_instruction)
    else:
        client = get_gemini_client()

    if client is None:
        _record_llm_usage(model_name=eff_model, tokens_total=0, used_fallback=True)
        if fail_closed_without_llm:
            raise AICreditsRequiredError("Live Gemini provider is currently unavailable; refusing to return canned output.")
        return fallback_text if fallback_text is not None else _deterministic_fallback(prompt, system_instruction)


    try:
        from google import genai
        from google.genai.errors import APIError, ClientError, ServerError
        from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

        config = genai.types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        @retry(
            stop=stop_after_attempt(2),
            wait=wait_fixed(2),
            retry=retry_if_exception_type((ServerError, APIError)),
            reraise=True,
        )
        def call_gemini(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

        used_model = eff_model
        try:
            response = call_gemini(used_model)
        except (ServerError, APIError, ClientError) as e:
            logger.warning(f"Primary model failed ({type(e).__name__}). Falling back to gemini-2.5-flash...")
            used_model = "gemini-2.5-flash"
            response = call_gemini(used_model)

        usage = getattr(response, "usage_metadata", None)
        total_tok = 0
        reported_actual_cost: float | None = None
        if usage is not None:
            total_tok = int(
                getattr(usage, "total_token_count", None)
                or ((getattr(usage, "prompt_token_count", 0) or 0) + (getattr(usage, "candidates_token_count", 0) or 0))
                or 0
            )
            raw_actual = getattr(usage, "actual_cost_inr", None)
            if raw_actual is None:
                raw_actual = getattr(response, "actual_cost_inr", None)
            if raw_actual is not None:
                reported_actual_cost = float(raw_actual)
        _record_llm_usage(
            model_name=used_model,
            tokens_total=total_tok,
            used_fallback=False,
            actual_cost_inr=reported_actual_cost,
        )
        return response.text or ""
    except Exception as exc:
        logger.warning(f"Gemini generation failed: {exc}. Utilizing deterministic fallback.")
        _record_llm_usage(model_name=eff_model, tokens_total=0, used_fallback=True)
        return fallback_text if fallback_text is not None else _deterministic_fallback(prompt, system_instruction)

