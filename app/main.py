import os
import time
import uuid
import json
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .logger import (
    configure_uvicorn_logging,
    log_sys, log_db, log_ingest, log_eval, log_perf,
)
from .schemas import (
    PromptVersionSchema,
    TraceSchema,
    LogUploadResponse,
    ToggleMissResponse,
)
from .database import (
    prompts_collection,
    traces_collection,
    missed_queries_collection,
    test_db_connection,
)
from .services.ingestion import analyze_log_sample, parse_plain_text_logs_to_traces
from .services.evaluator import evaluate_trace

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="evo_prompt API Hub", version="1.0.0")

# Hook our loggers into Uvicorn's internal logging immediately
configure_uvicorn_logging()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# PERF Middleware — times every request and logs to app.log
# ---------------------------------------------------------------------------
@app.middleware("http")
async def perf_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    log_perf(
        f"{request.method} {request.url.path} → {response.status_code} "
        f"({elapsed_ms:.1f} ms)"
    )
    return response

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_db_check():
    log_sys("Application startup — verifying MongoDB connectivity")
    db_ok = await test_db_connection()
    if not db_ok:
        log_sys(
            "MongoDB unreachable at startup — app will continue but DB ops will fail",
            level="warning",
        )
        return

    log_sys("MongoDB connection confirmed")

    try:
        count = await prompts_collection.count_documents({})
        log_db(f"prompts collection has {count} document(s)")
        if count == 0:
            seed_prompt = {
                "prompt_version_id": "seed-v1",
                "parent_version_id": None,
                "prompt_text": (
                    "You are a helpful coding assistant designed to execute system "
                    "tools to complete the user request. Adopt clean code parameters "
                    "and prioritize correctness."
                ),
                "metadata": {"is_active": True, "description": "Initial Seed System Prompt"},
                "created_at": datetime.utcnow(),
            }
            await prompts_collection.insert_one(seed_prompt)
            log_db("Seed system prompt (seed-v1) inserted")
    except Exception as e:
        log_db(f"Could not initialize seed data: {e}", level="error")


# ---------------------------------------------------------------------------
# PROMPT ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/prompts", response_model=List[PromptVersionSchema])
async def get_all_prompts():
    """Retrieve history of all system prompt versions."""
    t0 = time.perf_counter()
    cursor = prompts_collection.find({}).sort("created_at", -1)
    prompts = await cursor.to_list(length=100)
    log_db(f"get_all_prompts → {len(prompts)} record(s) ({(time.perf_counter()-t0)*1000:.1f} ms)")
    return prompts


@app.get("/api/prompts/active", response_model=PromptVersionSchema)
async def get_active_prompt():
    """Retrieve the currently active system prompt."""
    active = await prompts_collection.find_one({"metadata.is_active": True})
    if not active:
        active = await prompts_collection.find_one({}, sort=[("created_at", -1)])
    if not active:
        log_db("get_active_prompt — no prompts found", level="warning")
        raise HTTPException(status_code=404, detail="No system prompts found in registry.")
    log_db(f"get_active_prompt → {active.get('prompt_version_id')}")
    return active


@app.post("/api/prompts", response_model=PromptVersionSchema)
async def create_prompt(prompt_data: PromptVersionSchema):
    """Register a new system prompt version."""
    is_active = prompt_data.metadata.get("is_active", False)
    if is_active:
        await prompts_collection.update_many({}, {"$set": {"metadata.is_active": False}})
        log_db("Deactivated all existing prompts before inserting new active prompt")

    doc = prompt_data.dict()
    await prompts_collection.insert_one(doc)
    log_db(f"New prompt version inserted: {prompt_data.prompt_version_id}")
    return prompt_data


@app.post("/api/prompts/activate/{prompt_id}")
async def activate_prompt_by_id(prompt_id: str):
    """Swap the active flag to a target prompt ID."""
    exists = await prompts_collection.find_one({"prompt_version_id": prompt_id})
    if not exists:
        log_db(f"activate_prompt — prompt_id '{prompt_id}' not found", level="warning")
        raise HTTPException(status_code=404, detail="Prompt version not found.")

    await prompts_collection.update_many({}, {"$set": {"metadata.is_active": False}})
    await prompts_collection.update_one(
        {"prompt_version_id": prompt_id},
        {"$set": {"metadata.is_active": True}},
    )
    log_db(f"Active prompt swapped to '{prompt_id}'")
    return {"success": True, "message": f"Active prompt switched to {prompt_id}"}


# ---------------------------------------------------------------------------
# TRACE ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/traces")
async def get_traces(suggested_only: Optional[bool] = False):
    """Retrieve captured execution traces."""
    t0 = time.perf_counter()
    query = {"evaluation.suggested_miss": True} if suggested_only else {}
    cursor = traces_collection.find(query).sort("created_at", -1)
    traces = await cursor.to_list(length=100)

    for trace in traces:
        trace["_id"] = str(trace["_id"])
        miss_doc = await missed_queries_collection.find_one({"trace_id": trace.get("trace_id")})
        trace["is_manual_miss"] = miss_doc is not None
        if miss_doc:
            trace["manual_miss_reason"] = miss_doc.get("failure_reason", "")

    log_db(
        f"get_traces (suggested_only={suggested_only}) → {len(traces)} record(s) "
        f"({(time.perf_counter()-t0)*1000:.1f} ms)"
    )
    return traces


@app.post("/api/traces", response_model=TraceSchema)
async def ingest_trace(trace: TraceSchema):
    """Direct trace ingest route — invoked by application-level SDK interceptors."""
    # Attach active prompt if not supplied
    if not trace.prompt_version_id:
        active = await prompts_collection.find_one({"metadata.is_active": True})
        if active:
            trace.prompt_version_id = active.get("prompt_version_id")

    trace_doc = trace.dict()

    t0 = time.perf_counter()
    eval_result = evaluate_trace(trace_doc)
    log_perf(f"evaluate_trace for {trace.trace_id!r} took {(time.perf_counter()-t0)*1000:.1f} ms")

    trace_doc["evaluation"] = eval_result
    await traces_collection.insert_one(trace_doc)
    log_db(f"Trace {trace.trace_id!r} inserted (prompt={trace.prompt_version_id})")

    if eval_result["suggested_miss"]:
        miss_record = {
            "missed_query_id": str(uuid.uuid4()),
            "trace_id": trace.trace_id,
            "failure_reason": eval_result["failure_reason"],
            "evaluation_mode": eval_result["evaluation_mode"],
            "status": "pending",
            "created_at": datetime.utcnow(),
        }
        await missed_queries_collection.insert_one(miss_record)
        log_db(f"Auto-miss record created for trace {trace.trace_id!r}")

    return trace


# ---------------------------------------------------------------------------
# LOG UPLOAD & PREVIEW ENDPOINTS
# ---------------------------------------------------------------------------

@app.post("/api/logs/analyze")
async def analyze_uploaded_log_sample(file: UploadFile = File(...)):
    """Analyze the top 300 lines of an uploaded log file and return the inferred format."""
    log_ingest(f"Received log sample for analysis: '{file.filename}'")
    try:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8", errors="ignore")
        lines = content.splitlines()
        sample = lines[:300]
        format_type, parsed_items = analyze_log_sample(sample)
        log_ingest(f"Analysis complete: format='{format_type}' total_lines={len(lines)}")
        return {
            "success": True,
            "format_type": format_type,
            "total_lines": len(lines),
            "sample_parsed": parsed_items[:10],
        }
    except Exception as e:
        log_ingest(f"Log analysis failed for '{file.filename}': {e}", level="error")
        raise HTTPException(status_code=500, detail=f"Log file analysis failed: {str(e)}")


@app.post("/api/logs/upload", response_model=LogUploadResponse)
async def upload_log_file(file: UploadFile = File(...)):
    """Ingest a full log file, reconstruct traces, run evaluations, and persist results."""
    log_ingest(f"Log upload started: '{file.filename}'")
    try:
        t_upload = time.perf_counter()
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8", errors="ignore")

        sample_lines = content.splitlines()[:20]
        format_type, _ = analyze_log_sample(sample_lines)
        log_ingest(f"Detected format '{format_type}' for '{file.filename}'")

        traces_to_insert = []

        if format_type == "JSONL":
            for line in content.splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if "user_query" in data or "content" in data:
                        user_query = data.get("user_query") or data.get("content", [{}])[0].get("text", "unknown")
                        llm_response = data.get("llm_response") or data.get("content", "no response")
                        traces_to_insert.append({
                            "trace_id": data.get("trace_id", str(uuid.uuid4())),
                            "prompt_version_id": data.get("prompt_version_id", "seed-v1"),
                            "user_query": user_query,
                            "llm_response": str(llm_response),
                            "tool_calls": data.get("tool_calls", []),
                            "metadata": data.get("metadata", {"source": "uploaded_jsonl"}),
                            "created_at": datetime.utcnow(),
                        })
                except Exception:
                    continue
        else:
            traces_to_insert = parse_plain_text_logs_to_traces(content)

        log_ingest(f"Parsed {len(traces_to_insert)} candidate trace(s) from '{file.filename}'")

        success_count = 0
        failure_count = 0

        for raw_trace in traces_to_insert:
            try:
                trace_obj = TraceSchema(**raw_trace)
                trace_doc = trace_obj.dict()
                eval_result = evaluate_trace(trace_doc)
                trace_doc["evaluation"] = eval_result
                await traces_collection.insert_one(trace_doc)
                success_count += 1

                if eval_result["suggested_miss"]:
                    miss_record = {
                        "missed_query_id": str(uuid.uuid4()),
                        "trace_id": trace_obj.trace_id,
                        "failure_reason": eval_result["failure_reason"],
                        "evaluation_mode": eval_result["evaluation_mode"],
                        "status": "pending",
                        "created_at": datetime.utcnow(),
                    }
                    await missed_queries_collection.insert_one(miss_record)
            except Exception as e:
                log_ingest(f"Failed to ingest trace: {e}", level="error")
                failure_count += 1

        elapsed = (time.perf_counter() - t_upload) * 1000
        log_perf(f"Log upload '{file.filename}' complete — {success_count} inserted, {failure_count} failed ({elapsed:.0f} ms)")

        return LogUploadResponse(
            success=True,
            traces_parsed=success_count,
            failures=failure_count,
            message=f"Log file processed as {format_type}. {success_count} trace(s) ingested.",
        )
    except Exception as e:
        log_ingest(f"Log upload failed for '{file.filename}': {e}", level="error")
        raise HTTPException(status_code=500, detail=f"Log upload execution failed: {str(e)}")


# ---------------------------------------------------------------------------
# MISSED QUERY ENDPOINTS
# ---------------------------------------------------------------------------

@app.post("/api/missed_queries/toggle", response_model=ToggleMissResponse)
async def toggle_missed_query(
    trace_id: str = Form(...),
    reason: str = Form("Manual user override"),
):
    """Toggle manual flagging of a trace as a missed query (human-in-the-loop)."""
    trace = await traces_collection.find_one({"trace_id": trace_id})
    if not trace:
        log_db(f"toggle_missed_query — trace_id '{trace_id}' not found", level="warning")
        raise HTTPException(status_code=404, detail="Trace record not found.")

    existing = await missed_queries_collection.find_one({"trace_id": trace_id})

    if existing:
        await missed_queries_collection.delete_one({"trace_id": trace_id})
        log_db(f"Manual miss flag removed for trace '{trace_id}'")
        return ToggleMissResponse(
            success=True,
            is_miss=False,
            message="Trace 'Missed Query' flag removed.",
        )
    else:
        miss_record = {
            "missed_query_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "failure_reason": reason,
            "evaluation_mode": "manual",
            "status": "pending",
            "created_at": datetime.utcnow(),
        }
        await missed_queries_collection.insert_one(miss_record)
        log_db(f"Manual miss flag set for trace '{trace_id}'")
        return ToggleMissResponse(
            success=True,
            is_miss=True,
            message="Trace flagged as a Missed Query.",
        )


# ---------------------------------------------------------------------------
# STATIC CONTENT
# ---------------------------------------------------------------------------
os.makedirs("ui", exist_ok=True)
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")

log_sys("evo_prompt FastAPI application initialised")
