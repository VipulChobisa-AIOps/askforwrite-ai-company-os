# Common test utilities for mocking external services

import httpx
import pytest
from httpx import Response


@pytest.fixture
def httpx_mock(monkeypatch):
    """Patch httpx.AsyncClient.request to return deterministic mock responses.
    Extend the routing logic as needed for other services.
    """
    async def fake_request(method, url, *args, **kwargs):
        if "wordpress" in url:
            return Response(200, json={"id": 1234, "status": "published"})
        if "openai" in url or "gemini" in url:
            return Response(200, json={"choices": [{"message": {"content": "Generated content"}}]})
        raise RuntimeError(f"Unexpected external call: {method} {url}")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    return httpx.AsyncClient()

