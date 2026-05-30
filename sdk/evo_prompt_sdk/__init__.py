"""
evo_prompt_sdk
==============
Lightweight tracing wrapper for Google GenAI agents.

Usage
-----
    from google import genai
    from evo_prompt_sdk import EvoTracer

    client = genai.Client(api_key="...")
    tracer = EvoTracer(server_url="http://localhost:8000", prompt_version_id="v1")

    # Wrap the client — all generate_content calls are now traced
    traced_client = tracer.wrap_google(client)

    # Use traced_client exactly like the original
    response = traced_client.models.generate_content(
        model="gemini-2.0-flash",
        contents="What is the capital of France?"
    )
    print(response.text)

    # Explicitly mark a trace as a miss (optional)
    tracer.mark_miss(trace_id="...", reason="wrong answer")
"""

from .tracer import EvoTracer
from .dto.google_models import GoogleTracedClient

__all__ = ["EvoTracer", "GoogleTracedClient"]
__version__ = "0.1.0"
