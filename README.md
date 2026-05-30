# evo_prompt

Self-evolving system prompts for production AI agents — capture what your agent gets wrong, and let the prompt fix itself.




## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.12 recommended |
| MongoDB | 7.0+ | Must be running before `start.sh` |
| uv | latest | (Optional) `pip install uv` or [install guide](https://github.com/astral-sh/uv) |
| google-genai | 0.1.0+ | (Optional) Only required if using the SDK wrapper |

MongoDB installation (Ubuntu / Debian):
```bash
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update && sudo apt-get install -y mongodb-org
sudo systemctl start mongod
```

---

## Quickstart

**1. Start the backend**
```bash
git clone https://github.com/your-org/evo_prompt && cd evo_prompt
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash scripts/start.sh
```

**2. Instrument your agent**
```python
from google import genai
from evo_prompt_sdk import EvoTracer

client  = genai.Client(api_key="YOUR_API_KEY")
tracer  = EvoTracer(server_url="http://localhost:8000", prompt_version_id="v1")
client  = tracer.wrap_google(client)   # drop-in replacement
```

**3. Run your agent as normal**
```python
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[
        {"role": "user", "parts": [{"text": "What's the status of order #4821?"}]}
    ]
)
print(response.text)
# trace is already saved in the background
```

**4. Flag a bad response explicitly** *(optional)*
```python
# Call this anywhere in your app when you know the answer was wrong
tracer.mark_miss(trace_id="...", reason="Returned wrong order status")
```

**5. Open the dashboard**

Navigate to `http://localhost:8000` to review traces, inspect misses, and manage prompt versions.

---

## Installation

### Backend (observability server)

Requires Python 3.10+ and MongoDB.

```bash
git clone https://github.com/your-org/evo_prompt
cd evo_prompt

# Create virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Start MongoDB (if not already running)
sudo systemctl start mongod

# Start the server
bash scripts/start.sh
```

Server runs at `http://localhost:8000`. Dashboard is available at the same URL.

---

### SDK (agent instrumentation)

Install the tracing library into your agent project:

```bash
pip install -e ./sdk
```

Wrap your existing Google GenAI client with one line:

```python
from google import genai
from evo_prompt_sdk import EvoTracer

client = genai.Client(api_key="YOUR_API_KEY")
tracer = EvoTracer(server_url="http://localhost:8000")

# Drop-in replacement — behaves identically to the original client
client = tracer.wrap_google(client)

# Use as normal
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Summarise last quarter's revenue report"
)
print(response.text)
```

Every call is automatically traced. No changes to your agent logic required.

---

### Flagging a miss

Call `mark_miss()` anywhere in your application when you know a response was wrong:

```python
tracer.mark_miss(trace_id="...", reason="Hallucinated tool arguments")
```

Traces are also auto-flagged by the semantic evaluator when the model says things like *"I don't know"* or gets stuck in a tool loop.

---

## Features

### Trace capture
Intercepts `generate_content` calls (sync, async, and streaming) and records:
- User query — extracted from multi-turn `contents`, plain strings, or SDK Content objects
- Agent response — final text output or list of tool calls made
- Tool call chain — name, arguments, result, and errors for every tool invoked
- Latency — wall-clock time from request to response
- System prompt — captured from `system_instruction` at call time

### Miss detection
Every trace is evaluated automatically on ingest:
- **Semantic checks** — detects phrases like *"I cannot help with that"*, *"no appropriate tool"*, *"I don't know"*
- **Heuristic checks** — detects infinite tool loops (same tool + same args repeated 3+ times)
- **Manual flagging** — `mark_miss()` from your code, or one-click in the dashboard

### Prompt versioning
All system prompts are stored with full version history and parent lineage. Swap the active prompt from the dashboard — every agent picks it up on the next request without redeployment.

### Log file ingestion
Already have logs? Upload them directly:
- Auto-detects format: JSONL or plain-text (`TIMESTAMP : COMPONENT : LEVEL : MESSAGE`)
- Reconstructs traces from log lines using trigger-keyword heuristics
- Runs the same evaluator over ingested traces

### Structured logging
Application logs are written to `logs/` with tagged prefixes for easy filtering:

| Tag | Meaning |
|---|---|
| `[SYS]` | Startup, shutdown, configuration |
| `[DB]` | Database operations and query times |
| `[INGEST]` | Log parsing and trace reconstruction |
| `[EVAL]` | Evaluator decisions and miss flags |
| `[PERF]` | Request latency, computation time |
| `[AUTH]` | Authentication events (reserved) |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/prompts` | List all prompt versions |
| `POST` | `/api/prompts` | Register a new prompt version |
| `POST` | `/api/prompts/activate/{id}` | Set a prompt version as active |
| `GET` | `/api/traces` | Fetch captured traces (`?suggested_only=true` for misses) |
| `POST` | `/api/traces` | Ingest a trace directly (used by SDK) |
| `POST` | `/api/logs/analyze` | Preview format detection on a log file |
| `POST` | `/api/logs/upload` | Ingest a full log file |
| `POST` | `/api/missed_queries/toggle` | Toggle manual miss flag on a trace |

---

## Links

- [GEPA — Genetic Evolutionary Prompt Algorithm](https://arxiv.org/abs/2309.03409)
- [google-genai SDK](https://github.com/googleapis/python-genai)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io)
