"""
evo_prompt Logging Module
=========================
Provides structured, tag-based logging across the application.

Log Files:
  logs/app.log    — All application events (startup, DB, ingestion, eval, errors)
  logs/access.log — HTTP request/response access log (Uvicorn)

Log Tags (prefix every log line):
  [SYS]    — System-level events (startup, shutdown, config)
  [DB]     — Database operations (connect, query, insert, errors)
  [INGEST] — Log file ingestion pipeline (parse, reconstruct, format detection)
  [EVAL]   — Evaluator decisions (semantic checks, miss detection, heuristics)
  [PERF]   — Performance metrics (query time, response time, computation time)
  [AUTH]   — Authentication events (reserved for future use)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------
# Log directory setup
# ---------------------------------------------------------------------------
# Resolve logs/ relative to the project root (two levels up from this file)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

APP_LOG_PATH = os.path.join(LOGS_DIR, "app.log")
ACCESS_LOG_PATH = os.path.join(LOGS_DIR, "access.log")

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------
_APP_FMT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
_ACCESS_FMT = logging.Formatter(
    fmt="%(asctime)s | ACCESS | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)

# ---------------------------------------------------------------------------
# App logger  →  logs/app.log  +  stdout
# ---------------------------------------------------------------------------
app_logger = logging.getLogger("evo_prompt.app")
app_logger.setLevel(logging.DEBUG)
app_logger.propagate = False  # don't bubble up to root logger

_app_file_handler = RotatingFileHandler(
    APP_LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_app_file_handler.setFormatter(_APP_FMT)
app_logger.addHandler(_app_file_handler)

_app_stream_handler = logging.StreamHandler()
_app_stream_handler.setFormatter(_APP_FMT)
app_logger.addHandler(_app_stream_handler)

# ---------------------------------------------------------------------------
# Access logger  →  logs/access.log  ONLY  (no stdout duplication)
# ---------------------------------------------------------------------------
access_logger = logging.getLogger("evo_prompt.access")
access_logger.setLevel(logging.INFO)
access_logger.propagate = False

_access_file_handler = RotatingFileHandler(
    ACCESS_LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_access_file_handler.setFormatter(_ACCESS_FMT)
access_logger.addHandler(_access_file_handler)

# ---------------------------------------------------------------------------
# Redirect Uvicorn's own loggers into our files
# ---------------------------------------------------------------------------
def configure_uvicorn_logging() -> None:
    """
    Hook Uvicorn's internal loggers so that:
      - uvicorn.access  →  access.log
      - uvicorn.error   →  app.log  (non-HTTP errors, startup messages)
    Call this once after the app is created.
    """
    # --- access ---
    uv_access = logging.getLogger("uvicorn.access")
    uv_access.handlers.clear()
    uv_access.propagate = False
    uv_access.addHandler(_access_file_handler)

    # --- error / general ---
    uv_error = logging.getLogger("uvicorn.error")
    uv_error.handlers.clear()
    uv_error.propagate = False
    uv_error.addHandler(_app_file_handler)
    uv_error.addHandler(_app_stream_handler)

    # --- root uvicorn (catches anything not caught above) ---
    uv_root = logging.getLogger("uvicorn")
    uv_root.handlers.clear()
    uv_root.propagate = False
    uv_root.addHandler(_app_file_handler)
    uv_root.addHandler(_app_stream_handler)


# ---------------------------------------------------------------------------
# Tag-based helper functions
# ---------------------------------------------------------------------------

def log_sys(msg: str, level: str = "info") -> None:
    """System-level operations: startup, shutdown, configuration."""
    getattr(app_logger, level)("[SYS] %s", msg)

def log_db(msg: str, level: str = "info") -> None:
    """Database operations: connect, query, insert, delete, errors."""
    getattr(app_logger, level)("[DB] %s", msg)

def log_ingest(msg: str, level: str = "info") -> None:
    """Ingestion pipeline: format detection, parsing, trace reconstruction."""
    getattr(app_logger, level)("[INGEST] %s", msg)

def log_eval(msg: str, level: str = "info") -> None:
    """Evaluator: semantic failure checks, heuristic miss detection."""
    getattr(app_logger, level)("[EVAL] %s", msg)

def log_perf(msg: str, level: str = "info") -> None:
    """Performance: query times, response times, computation durations."""
    getattr(app_logger, level)("[PERF] %s", msg)

def log_auth(msg: str, level: str = "info") -> None:
    """Authentication: login, token validation, permission checks."""
    getattr(app_logger, level)("[AUTH] %s", msg)
