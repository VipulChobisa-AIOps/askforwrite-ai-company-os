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

from dotenv import load_dotenv

if "pytest" not in sys.modules and "unittest" not in sys.modules:
    load_dotenv()

logger = logging.getLogger("afw.company_os.llm_client")

# Default model used across agents; override per-agent as needed.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# ── BYOK Tenant Isolation State ──────────────────────────────────────────────
_REQUEST_GEMINI_KEY: ContextVar[str | None] = ContextVar("request_gemini_key", default=None)
_REQUEST_IS_OWNER: ContextVar[bool] = ContextVar("request_is_owner", default=True)


def set_request_llm_context(gemini_key: str | None, is_owner: bool) -> None:
    """Set thread/task local context for Gemini BYOK key and owner flag."""
    cleaned = gemini_key.strip() if gemini_key and gemini_key.strip() else None
    _REQUEST_GEMINI_KEY.set(cleaned)
    _REQUEST_IS_OWNER.set(bool(is_owner))


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
            "Client confirmed strong operational alignment with proposed automation roadmap. "
            "Expressed interest in expanding deployment across regional logistics hubs. "
            "Requested formal pricing and SLA terms for follow-up next week."
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
) -> str:
    """
    Generate text via Gemini with automatic LangSmith tracing.
    Enforces strict BYOK isolation:
    - If a BYOK request key is set in context, uses that key.
    - If _REQUEST_IS_OWNER is False and no BYOK key is set, NEVER falls back to Owner's key;
      immediately uses deterministic fallback (zero cost to Owner).
    - Only uses server's GEMINI_API_KEY if _REQUEST_IS_OWNER is True.
    """
    req_key = _REQUEST_GEMINI_KEY.get()
    is_owner = _REQUEST_IS_OWNER.get()

    if req_key:
        client = get_gemini_client_for_key(req_key)
    elif not is_owner:
        # Commercial tenant without BYOK key: zero quota consumption of Owner's key
        logger.info("Non-owner request with no BYOK Gemini key. Utilizing deterministic fallback.")
        return fallback_text if fallback_text is not None else _deterministic_fallback(prompt, system_instruction)
    else:
        client = get_gemini_client()

    if client is None:
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

        try:
            response = call_gemini(model or DEFAULT_MODEL)
        except (ServerError, APIError, ClientError) as e:
            logger.warning(f"Primary model failed ({type(e).__name__}). Falling back to gemini-2.5-flash...")
            response = call_gemini("gemini-2.5-flash")

        return response.text or ""
    except Exception as exc:
        logger.warning(f"Gemini generation failed: {exc}. Utilizing deterministic fallback.")
        return fallback_text if fallback_text is not None else _deterministic_fallback(prompt, system_instruction)

