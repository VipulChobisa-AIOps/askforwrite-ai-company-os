"""
LangSmith Quickstart with Google GenAI
======================================
Tests Google GenAI integration and LangSmith tracing in AskforWrite AI Company OS.
"""

from pathlib import Path
from dotenv import load_dotenv
from google import genai
from langsmith import wrappers

# Load environment variables from os_gateway/.env
env_file = Path(__file__).resolve().parent.parent / ".env"
if not env_file.exists():
    env_file = Path(__file__).resolve().parent / "os_gateway" / ".env"
load_dotenv(dotenv_path=env_file)
load_dotenv()


def main():
    # genai.Client() automatically reads GOOGLE_API_KEY / GEMINI_API_KEY from the environment
    gemini_client = genai.Client()

    # Wrap the Gemini client to enable LangSmith tracing
    client = wrappers.wrap_gemini(
        gemini_client,
        tracing_extra={
            "tags": ["gemini", "python", "os_gateway"],
            "metadata": {
                "integration": "google-genai",
                "system": "AskforWrite AI Company OS",
            },
        },
    )

    print("Sending traced prompt to Gemini...")
    # Make a traced Gemini call
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents="Explain quantum computing in simple terms.",
    )

    print("\n--- Response from Gemini ---")
    print(response.text)
    print("\n--- LangSmith Trace ---")
    print("Trace logged to project: os_gateway (https://smith.langchain.com)")


if __name__ == "__main__":
    main()
