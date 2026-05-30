import os
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from .logger import log_db, log_sys

# Get MongoDB Connection URI from environment or use local default
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")

log_sys(f"Initializing MongoDB client → {MONGO_URI}")
client = AsyncMongoClient(MONGO_URI)
db = client.evo_prompt

# Expose Collections
prompts_collection = db.prompts
traces_collection = db.traces
missed_queries_collection = db.missed_queries

log_db("Collections bound: prompts, traces, missed_queries")

async def test_db_connection() -> bool:
    """Lightweight ping to verify the database is responsive."""
    try:
        await db.command("ping")
        log_db("Ping successful — MongoDB is reachable")
        return True
    except Exception as e:
        log_db(f"Ping failed: {e}", level="error")
        return False
