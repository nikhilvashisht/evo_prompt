"""
test_google_wrapper.py
======================
Minimal smoke test for the Google GenAI wrapper.
Does NOT make real API calls — mocks the google-genai client.

Run with:
    python sdk/tests/test_google_wrapper.py
"""

import sys
import asyncio
import threading
import time
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, "sdk")
from evo_prompt_sdk import EvoTracer

# ---------------------------------------------------------------------------
# Build a mock google.genai response
# ---------------------------------------------------------------------------

def _make_mock_response(text="Paris is the capital of France.", tool_calls=None):
    part = MagicMock()
    part.text = text
    part.function_call = None

    if tool_calls:
        parts = []
        for tc in tool_calls:
            p = MagicMock()
            p.text = None
            fc = MagicMock()
            fc.name = tc["name"]
            fc.args = tc["args"]
            p.function_call = fc
            parts.append(p)
        content = MagicMock()
        content.parts = parts
    else:
        content = MagicMock()
        content.parts = [part]

    candidate = MagicMock()
    candidate.content = content

    response = MagicMock()
    response.text = text
    response.candidates = [candidate]
    return response


# ---------------------------------------------------------------------------
# Test 1: Sync generate_content
# ---------------------------------------------------------------------------

def test_sync_generate_content():
    print("\n[TEST 1] Sync generate_content ...")

    mock_client = MagicMock()
    mock_response = _make_mock_response("Paris is the capital of France.")
    mock_client.models.generate_content.return_value = mock_response

    posted = []

    tracer = EvoTracer(server_url="http://localhost:8000", prompt_version_id="test-v1")

    # Patch send_trace to capture without HTTP
    original_send = tracer.send_trace
    def capture_trace(trace):
        posted.append(trace)
        return trace.get("trace_id")
    tracer.send_trace = capture_trace

    tclient = tracer.wrap_google(mock_client)
    resp = tclient.models.generate_content(
        model="gemini-2.0-flash",
        contents="What is the capital of France?"
    )

    assert resp.text == "Paris is the capital of France."
    assert len(posted) == 1
    trace = posted[0]
    assert trace["user_query"] == "What is the capital of France?"
    assert trace["llm_response"] == "Paris is the capital of France."
    assert trace["prompt_version_id"] == "test-v1"
    assert trace["metadata"]["provider"] == "google-genai"
    assert trace["metadata"]["model"] == "gemini-2.0-flash"
    print("  ✓ Response returned correctly")
    print("  ✓ Trace captured:", trace["user_query"][:50])
    print("  ✓ Latency recorded:", trace["metadata"]["latency_ms"], "ms")


# ---------------------------------------------------------------------------
# Test 2: Tool call extraction
# ---------------------------------------------------------------------------

def test_tool_call_extraction():
    print("\n[TEST 2] Tool call extraction ...")

    mock_client = MagicMock()
    mock_response = _make_mock_response(
        text=None,
        tool_calls=[{"name": "search_web", "args": {"query": "capital of France"}}]
    )
    mock_response.text = None
    mock_client.models.generate_content.return_value = mock_response

    posted = []
    tracer = EvoTracer()
    tracer.send_trace = lambda t: posted.append(t)

    tclient = tracer.wrap_google(mock_client)
    tclient.models.generate_content(
        model="gemini-2.0-flash",
        contents="What is the capital of France?"
    )

    assert len(posted) == 1
    trace = posted[0]
    assert len(trace["tool_calls"]) == 1
    assert trace["tool_calls"][0]["tool_name"] == "search_web"
    assert trace["tool_calls"][0]["arguments"] == {"query": "capital of France"}
    print("  ✓ Tool call captured:", trace["tool_calls"][0])


# ---------------------------------------------------------------------------
# Test 3: Async generate_content
# ---------------------------------------------------------------------------

async def _run_async_test():
    mock_client = MagicMock()
    mock_client.aio = MagicMock()
    mock_response = _make_mock_response("Async response!")
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    posted = []
    tracer = EvoTracer()
    tracer.send_trace = lambda t: posted.append(t)

    tclient = tracer.wrap_google(mock_client)
    resp = await tclient.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents="Async query?"
    )

    assert resp.text == "Async response!"
    assert len(posted) == 1
    assert posted[0]["user_query"] == "Async query?"
    assert posted[0]["llm_response"] == "Async response!"
    return posted[0]


def test_async_generate_content():
    print("\n[TEST 3] Async generate_content ...")
    trace = asyncio.run(_run_async_test())
    print("  ✓ Async trace captured:", trace["user_query"])
    print("  ✓ Response:", trace["llm_response"])


# ---------------------------------------------------------------------------
# Test 4: mark_miss (fire-and-forget)
# ---------------------------------------------------------------------------

def test_mark_miss():
    print("\n[TEST 4] mark_miss ...")

    calls = []
    tracer = EvoTracer()
    tracer._post_miss = lambda tid, r: calls.append((tid, r))

    tracer.mark_miss("trace-abc-123", reason="Agent gave wrong answer")
    time.sleep(0.05)  # give the background thread time to run

    # Note: _post_miss runs in a thread but we patched it to be sync
    # The thread will call _post_miss — let's just verify no exception raised
    print("  ✓ mark_miss called without raising (fire-and-forget)")


# ---------------------------------------------------------------------------
# Test 5: Multi-turn contents extraction
# ---------------------------------------------------------------------------

def test_multi_turn_extraction():
    print("\n[TEST 5] Multi-turn contents — last user message extracted ...")

    mock_client = MagicMock()
    mock_response = _make_mock_response("Sure, it's 4PM.")
    mock_client.models.generate_content.return_value = mock_response

    posted = []
    tracer = EvoTracer()
    tracer.send_trace = lambda t: posted.append(t)

    tclient = tracer.wrap_google(mock_client)
    tclient.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            {"role": "user",  "parts": [{"text": "Hello!"}]},
            {"role": "model", "parts": [{"text": "Hi there!"}]},
            {"role": "user",  "parts": [{"text": "What time is it?"}]},
        ]
    )

    assert posted[0]["user_query"] == "What time is it?"
    print("  ✓ Correctly extracted last user turn:", posted[0]["user_query"])


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  evo_prompt_sdk — Google wrapper smoke tests")
    print("=" * 55)

    test_sync_generate_content()
    test_tool_call_extraction()
    test_async_generate_content()
    test_mark_miss()
    test_multi_turn_extraction()

    print("\n" + "=" * 55)
    print("  All tests passed ✓")
    print("=" * 55)
