from typing import Dict, Any, List, Tuple
from ..logger import log_eval

# Core list of semantic expressions indicating the agent failed to resolve a query or find a tool
SEMANTIC_FAILURE_MARKERS = [
    "i do not know",
    "i don't know",
    "cannot find an answer",
    "no appropriate tool",
    "tool is not available",
    "apologize, but i am unable",
    "unsupported operation",
    "sorry, i cannot",
    "unable to help",
    "invalid tool",
    "could not execute",
    "not programmed to",
]

def check_semantic_failures(llm_response: str) -> Tuple[bool, str]:
    """Inspects LLM text completions for semantic markers indicating a failure."""
    if not llm_response:
        return False, ""

    normalized = llm_response.lower()
    for marker in SEMANTIC_FAILURE_MARKERS:
        if marker in normalized:
            log_eval(f"Semantic failure marker matched: '{marker}'", level="warning")
            return True, f"Semantic Failure (Match: '{marker}')"

    return False, ""

def check_heuristic_failures(tool_calls: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Analyses the tool call stack for exceptions or stuck loops."""
    if not tool_calls:
        return False, ""

    # Direct exception in any tool result
    for tc in tool_calls:
        if tc.get("error"):
            msg = f"Tool exception in '{tc.get('tool_name')}': {tc.get('error')}"
            log_eval(msg, level="warning")
            return True, msg

    # Stuck-loop detection: same tool + same args repeated 3+ consecutive times
    if len(tool_calls) >= 3:
        last_three = tool_calls[-3:]
        ref = last_three[0]
        if all(
            tc.get("tool_name") == ref.get("tool_name")
            and tc.get("arguments") == ref.get("arguments")
            for tc in last_three[1:]
        ):
            msg = f"Infinite loop warning — '{ref.get('tool_name')}' repeated 3× with identical args"
            log_eval(msg, level="warning")
            return True, msg

    return False, ""

def evaluate_trace(trace_data: Dict[str, Any]) -> Dict[str, Any]:
    """Runs semantic and heuristic rules over a trace and returns auto-flagging suggestions."""
    llm_response = trace_data.get("llm_response", "")
    tool_calls = trace_data.get("tool_calls", [])
    trace_id = trace_data.get("trace_id", "unknown")

    log_eval(f"Evaluating trace {trace_id!r} — {len(tool_calls)} tool call(s)")

    sem_failed, sem_reason = check_semantic_failures(llm_response)
    heur_failed, heur_reason = check_heuristic_failures(tool_calls)

    suggested_miss = sem_failed or heur_failed
    reasons = [r for r in [sem_reason, heur_reason] if r]
    failure_reason = " & ".join(reasons) if suggested_miss else "No failures detected"
    mode = "semantic" if sem_failed else ("heuristic" if heur_failed else "ok")

    if suggested_miss:
        log_eval(f"Trace {trace_id!r} flagged as potential miss — {failure_reason}", level="warning")
    else:
        log_eval(f"Trace {trace_id!r} passed all checks")

    return {
        "suggested_miss": suggested_miss,
        "failure_reason": failure_reason,
        "evaluation_mode": mode,
    }
