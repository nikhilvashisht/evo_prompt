"""
tracer.py — Core EvoTracer class
=================================
Responsible for:
  - Sending completed traces to the evo_prompt backend
  - Explicit miss/ok marking after the fact
  - Wrapping provider clients
"""

from __future__ import annotations

import uuid
import time
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import httpx


class EvoTracer:
    """
    Central tracer. Instantiate once per agent process.

    Parameters
    ----------
    server_url : str
        Base URL of the running evo_prompt backend.
        Default: http://localhost:8000
    prompt_version_id : str | None
        Which prompt version to tag traces with.
        If None, the backend will attach the currently active prompt.
    timeout : float
        HTTP timeout for sending traces (seconds). Default: 3.0
        Failures are silently swallowed so they never affect the agent.
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        prompt_version_id: Optional[str] = None,
        timeout: float = 3.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.prompt_version_id = prompt_version_id
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Provider wrappers
    # ------------------------------------------------------------------

    def wrap_google(self, client: Any) -> Any:
        """
        Returns a wrapped version of the google-genai Client.
        The wrapper intercepts all generate_content calls (sync + async)
        and records traces, without changing any of the client's behaviour
        or return values.

        Parameters
        ----------
        client : google.genai.Client
            Your existing genai.Client instance.

        Returns
        -------
        GoogleTracedClient
            A thin proxy that behaves identically to the original client.
        """
        from .google_wrapper import GoogleTracedClient
        return GoogleTracedClient(client=client, tracer=self)

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    def _make_trace_id(self) -> str:
        return str(uuid.uuid4())

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def send_trace(self, trace: dict) -> str:
        """
        POST a completed trace to the backend.
        Always fire-and-forget in a background thread so the agent is
        never blocked by network latency or backend unavailability.

        Returns the trace_id that was sent.
        """
        trace_id = trace.setdefault("trace_id", self._make_trace_id())
        trace.setdefault("created_at", self._now_iso())
        if self.prompt_version_id and not trace.get("prompt_version_id"):
            trace["prompt_version_id"] = self.prompt_version_id

        threading.Thread(
            target=self._post_trace,
            args=(trace,),
            daemon=True,
        ).start()
        return trace_id

    def _post_trace(self, trace: dict) -> None:
        """Blocking HTTP POST — runs in background thread."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                client.post(f"{self.server_url}/api/traces", json=trace)
        except Exception:
            # Never surface network errors to the agent
            pass

    # ------------------------------------------------------------------
    # Explicit outcome signals
    # ------------------------------------------------------------------

    def mark_miss(self, trace_id: str, reason: str = "Manually marked") -> None:
        """
        Explicitly flag a completed trace as a miss.
        Call this from your application logic when you know the response
        was wrong or unsatisfactory.

        Parameters
        ----------
        trace_id : str
            The trace_id returned by send_trace (or from the wrapper).
        reason : str
            Human-readable explanation of why it was a miss.
        """
        threading.Thread(
            target=self._post_miss,
            args=(trace_id, reason),
            daemon=True,
        ).start()

    def mark_ok(self, trace_id: str) -> None:
        """
        Explicitly confirm a trace outcome was acceptable.
        Useful for background agents where you can verify the artifact
        produced was accepted downstream.
        """
        threading.Thread(
            target=self._post_ok,
            args=(trace_id,),
            daemon=True,
        ).start()

    def _post_miss(self, trace_id: str, reason: str) -> None:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                client.post(
                    f"{self.server_url}/api/missed_queries/toggle",
                    data={"trace_id": trace_id, "reason": reason},
                )
        except Exception:
            pass

    def _post_ok(self, trace_id: str) -> None:
        # For now, ok is a no-op at the API level — it's the absence of a miss.
        # Reserved for future explicit acceptance signals.
        pass
