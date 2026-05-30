from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid

# Helper to generate string-based UUIDs
def make_uuid() -> str:
    return str(uuid.uuid4())

class PromptVersionSchema(BaseModel):
    prompt_version_id: str = Field(default_factory=make_uuid)
    parent_version_id: Optional[str] = None
    prompt_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ToolCallSchema(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None

class TraceSchema(BaseModel):
    trace_id: str = Field(default_factory=make_uuid)
    prompt_version_id: Optional[str] = None
    user_query: str
    llm_response: Optional[str] = None
    raw_thoughts: Optional[str] = None
    tool_calls: List[ToolCallSchema] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class MissedQuerySchema(BaseModel):
    missed_query_id: str = Field(default_factory=make_uuid)
    trace_id: str
    failure_reason: str
    evaluation_mode: str = "manual"  # "manual", "semantic", "llm-judge"
    status: str = "pending"          # "pending", "reviewed", "resolved"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# API Request/Response Schemas
class LogUploadResponse(BaseModel):
    success: bool
    traces_parsed: int
    failures: int
    message: str

class ToggleMissResponse(BaseModel):
    success: bool
    is_miss: bool
    message: str
