"""
Centralized LLM client with LangSmith tracing.
================================================
Provides a singleton-style Gemini client wrapped with LangSmith telemetry,
used by all AI-powered agents in the Company OS.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from google import genai
from langsmith import traceable, wrappers

load_dotenv()

# Default model used across agents; override per-agent as needed.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


@lru_cache(maxsize=1)
def get_gemini_client():
    """Return a LangSmith-wrapped Gemini client (singleton)."""
    raw_client = genai.Client()
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


@traceable(name="gemini_generate", run_type="llm")
def generate(
    prompt: str,
    *,
    model: str | None = None,
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
) -> str:
    """
    Generate text via Gemini with automatic LangSmith tracing.

    All agent calls should go through this function so every LLM interaction
    is traced, measured, and reproducible in LangSmith.
    """
    client = get_gemini_client()
    config = genai.types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    if system_instruction:
        config.system_instruction = system_instruction

    from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
    from google.genai.errors import ServerError, ClientError, APIError

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_fixed(5), 
        retry=retry_if_exception_type((ServerError, APIError)),
        reraise=True
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
        print(f"Warning: Primary model failed ({type(e).__name__}). Falling back to gemini-3.5-flash...")
        response = call_gemini("gemini-3.5-flash")

    return response.text or ""
