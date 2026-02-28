import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    session_id: str | None = None
    workspace: str | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[Choice]
    usage: Usage = Usage()


class DeltaMessage(BaseModel):
    role: str | None = None
    content: str | None = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "local"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class DocumentIngestResponse(BaseModel):
    doc_id: str
    job_id: str
    file_name: str
    workspace: str
    original_size: int
    compressed_size: int
    status: str


class CodebaseIngestResponse(BaseModel):
    doc_id: str
    job_id: str
    workspace: str
    archive_name: str
    original_size: int
    compressed_size: int
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    doc_id: str
    workspace: str
    job_type: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: dict | None = None
    attempts: int = 0


class SessionInfo(BaseModel):
    id: str
    workspace: str
    model: str
    turn_count: int
    created_at: str
    updated_at: str
    summary: str | None = None
