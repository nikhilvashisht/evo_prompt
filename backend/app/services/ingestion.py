import re
import json
from typing import List, Dict, Any, Tuple
from ..schemas import TraceSchema, ToolCallSchema
from ..logger import log_ingest

# Regular expression matching user's standard log pattern:
# TIMESTAMP : COMPONENT : LEVEL : MESSAGE
LOG_PATTERN = re.compile(
    r"^([\d\-T\:\.\+\-Z ]+)\s*:\s*([^:]+)\s*:\s*\[?(INFO|WARN|ERROR|DEBUG|CRITICAL)\]?\s*:\s*(.*)$",
    re.IGNORECASE
)

def analyze_log_sample(sample_lines: List[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """Analyzes the first few lines of a log file to infer format and return sample parsed items."""
    log_ingest(f"Analyzing sample of {len(sample_lines)} lines for format detection")
    parsed_items = []
    is_jsonl = True

    # Try parsing as JSONL first
    non_empty_lines = [line.strip() for line in sample_lines if line.strip()]
    if not non_empty_lines:
        log_ingest("Sample is empty — no lines to analyze", level="warning")
        return "Empty Log File", []

    for line in non_empty_lines[:10]:
        try:
            json.loads(line)
        except Exception:
            is_jsonl = False
            break

    if is_jsonl:
        for line in non_empty_lines[:20]:
            try:
                data = json.loads(line)
                parsed_items.append({"raw": line, "parsed": data, "success": True})
            except Exception as e:
                parsed_items.append({"raw": line, "parsed": None, "success": False, "error": str(e)})
        log_ingest(f"Format detected: JSONL ({len(parsed_items)} sample rows parsed)")
        return "JSONL", parsed_items

    log_ingest("JSONL detection failed — falling back to plain-text delimiter pattern")
    # Fall back to custom TIMESTAMP : COMPONENT : LEVEL : MESSAGE
    for line in non_empty_lines[:20]:
        match = LOG_PATTERN.match(line)
        if match:
            timestamp, component, level, message = match.groups()
            parsed_items.append({
                "raw": line,
                "parsed": {
                    "timestamp": timestamp.strip(),
                    "component": component.strip(),
                    "level": level.strip(),
                    "message": message.strip()
                },
                "success": True
            })
        else:
            parsed_items.append({
                "raw": line,
                "parsed": None,
                "success": False,
                "error": "Line did not match TIMESTAMP : COMPONENT : LEVEL : MESSAGE pattern"
            })

    matched = sum(1 for item in parsed_items if item["success"])
    log_ingest(f"Format detected: Plain Text — {matched}/{len(parsed_items)} sample lines matched pattern")
    return "Plain Text (Delimiter-based)", parsed_items


def parse_plain_text_logs_to_traces(content: str) -> List[Dict[str, Any]]:
    """Ingests a large block of plain text log lines, reconstructs Trace records
    by identifying execution triggers, tools, and response boundaries.
    """
    lines = content.splitlines()
    log_ingest(f"Starting plain-text reconstruction — {len(lines)} total lines")
    traces = []

    current_query = None
    current_response = ""
    current_tools = []
    current_component = ""

    for line_idx, line in enumerate(lines):
        if not line.strip():
            continue

        match = LOG_PATTERN.match(line.strip())
        if not match:
            # Multi-line message content continuation
            if current_query:
                current_response += "\n" + line.strip()
            continue

        timestamp_str, component, level, message = match.groups()
        component = component.strip()
        message = message.strip()

        # Look for agent/LLM activity triggers in message
        is_query_trigger = any(x in message.lower() for x in ["user query:", "input prompt:", "query:"])
        is_tool_call_trigger = any(x in message.lower() for x in ["calling tool", "executing tool"])
        is_tool_result_trigger = any(x in message.lower() for x in ["tool result", "tool returned"])
        is_llm_response_trigger = any(x in message.lower() for x in ["llm response:", "model output:", "agent response:"])

        if is_query_trigger:
            if current_query:
                log_ingest(f"Committing trace — query='{current_query[:60]}' tools={len(current_tools)}")
                traces.append({
                    "user_query": current_query,
                    "llm_response": current_response.strip(),
                    "tool_calls": current_tools,
                    "metadata": {"parsed_component": current_component, "source": "plain_text_logs"}
                })
            current_query = message.split(":", 1)[-1].strip() if ":" in message else message
            current_response = ""
            current_tools = []
            current_component = component
            log_ingest(f"New trace started — component='{component}' query='{current_query[:60]}'")

        elif is_tool_call_trigger:
            tool_name = "unknown"
            args = {}
            tool_match = re.search(r"tool:?\s*([\w\-]+)", message, re.IGNORECASE)
            if tool_match:
                tool_name = tool_match.group(1)
            args_match = re.search(r"args:?\s*(\{.*\})", message, re.IGNORECASE)
            if args_match:
                try:
                    args = json.loads(args_match.group(1).replace("'", '"'))
                except Exception:
                    args = {"raw_args": args_match.group(1)}

            log_ingest(f"Tool call detected: '{tool_name}' args={list(args.keys())}")
            current_tools.append({
                "tool_name": tool_name,
                "arguments": args,
                "result": None,
                "error": None
            })

        elif is_tool_result_trigger:
            if current_tools:
                result_val = message.split(":", 1)[-1].strip() if ":" in message else message
                current_tools[-1]["result"] = result_val
                if level.upper() in ["ERROR", "CRITICAL"]:
                    current_tools[-1]["error"] = result_val
                    log_ingest(
                        f"Tool error recorded for '{current_tools[-1]['tool_name']}': {result_val[:80]}",
                        level="warning"
                    )

        elif is_llm_response_trigger:
            resp_val = message.split(":", 1)[-1].strip() if ":" in message else message
            current_response += "\n" + resp_val

        else:
            if current_query:
                current_response += f"\n[{component}] {message}"

    # Commit any dangling trace
    if current_query:
        log_ingest(f"Committing final trace — query='{current_query[:60]}' tools={len(current_tools)}")
        traces.append({
            "user_query": current_query,
            "llm_response": current_response.strip(),
            "tool_calls": current_tools,
            "metadata": {"parsed_component": current_component, "source": "plain_text_logs"}
        })

    log_ingest(f"Reconstruction complete — {len(traces)} trace(s) extracted")
    return traces
