"""
dto/google_models.py — Proxy model classes for Google GenAI tracing
====================================================================
Contains the transparent proxy objects that wrap google-genai's
models/aio namespaces and intercept generate_content calls.

These are data-transfer / structural objects — they hold no extraction
logic. All extraction is handled in google_wrapper.py.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..tracer import EvoTracer
    from ..google_wrapper import _build_trace


class TracedModels:
    """Proxies client.models — intercepts sync generate_content calls."""

    def __init__(self, original_models: Any, tracer: "EvoTracer") -> None:
        self._models = original_models
        self._tracer = tracer

    def generate_content(self, *args, **kwargs) -> Any:
        from ..google_wrapper import _build_trace
        start_time = time.perf_counter()
        response = self._models.generate_content(*args, **kwargs)
        latency_ms = (time.perf_counter() - start_time) * 1000
        trace = _build_trace(self._tracer, args, kwargs, response, latency_ms)
        self._tracer.send_trace(trace)
        return response

    def generate_content_stream(self, *args, **kwargs):
        """
        Sync streaming: accumulate chunks transparently, then send a single
        trace once the stream is fully consumed.
        """
        from ..google_wrapper import _build_trace
        start_time = time.perf_counter()
        stream = self._models.generate_content_stream(*args, **kwargs)
        chunks = []

        def _gen():
            for chunk in stream:
                chunks.append(chunk)
                yield chunk
            latency_ms = (time.perf_counter() - start_time) * 1000
            last = chunks[-1] if chunks else None
            if last is not None:
                trace = _build_trace(self._tracer, args, kwargs, last, latency_ms)
                trace["llm_response"] = "".join(
                    getattr(c, "text", "") or "" for c in chunks
                )
                self._tracer.send_trace(trace)

        return _gen()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)


class TracedAioModels:
    """Proxies client.aio.models — intercepts async generate_content calls."""

    def __init__(self, original_models: Any, tracer: "EvoTracer") -> None:
        self._models = original_models
        self._tracer = tracer

    async def generate_content(self, *args, **kwargs) -> Any:
        from ..google_wrapper import _build_trace
        start_time = time.perf_counter()
        response = await self._models.generate_content(*args, **kwargs)
        latency_ms = (time.perf_counter() - start_time) * 1000
        trace = _build_trace(self._tracer, args, kwargs, response, latency_ms)
        self._tracer.send_trace(trace)
        return response

    async def generate_content_stream(self, *args, **kwargs):
        """
        Async streaming: yield chunks transparently, send trace after exhaustion.
        """
        from ..google_wrapper import _build_trace
        start_time = time.perf_counter()
        chunks = []

        async for chunk in await self._models.generate_content_stream(*args, **kwargs):
            chunks.append(chunk)
            yield chunk

        latency_ms = (time.perf_counter() - start_time) * 1000
        last = chunks[-1] if chunks else None
        if last is not None:
            trace = _build_trace(self._tracer, args, kwargs, last, latency_ms)
            trace["llm_response"] = "".join(
                getattr(c, "text", "") or "" for c in chunks
            )
            self._tracer.send_trace(trace)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)


class TracedAio:
    """Proxies client.aio — exposes TracedAioModels at .models."""

    def __init__(self, original_aio: Any, tracer: "EvoTracer") -> None:
        self._aio = original_aio
        self.models = TracedAioModels(original_aio.models, tracer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._aio, name)


class GoogleTracedClient:
    """
    Transparent proxy around google.genai.Client.

    All generate_content calls (sync / async / streaming) are intercepted
    and traced. Everything else is forwarded to the original client unchanged.

    Example
    -------
        from google import genai
        from evo_prompt_sdk import EvoTracer

        client  = genai.Client(api_key="...")
        tracer  = EvoTracer(server_url="http://localhost:8000")
        tclient = tracer.wrap_google(client)

        resp = tclient.models.generate_content(
            model="gemini-2.0-flash",
            contents="Hello!"
        )
        print(resp.text)
    """

    def __init__(self, client: Any, tracer: "EvoTracer") -> None:
        self._client = client
        self._tracer = tracer
        self.models = TracedModels(client.models, tracer)
        if hasattr(client, "aio") and hasattr(client.aio, "models"):
            self.aio = TracedAio(client.aio, tracer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
