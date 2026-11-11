from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MessageStatus = Literal["complete", "streaming", "cancelled", "error"]
Theme = Literal["system", "light", "dark"]


class Conversation(BaseModel):
    id: str
    title: str
    model_id: str | None
    archived: bool
    workspace_id: str = "genel"
    parent_id: str | None = None
    created_at: str
    updated_at: str
    match_snippet: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model_id: str | None = Field(default=None, max_length=200)
    workspace_id: str = Field(default="genel", min_length=1, max_length=80)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None
    model_id: str | None = Field(default=None, max_length=200)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=80)


class MessageSource(BaseModel):
    kind: Literal["memory", "document"]
    id: str
    title: str
    path: str | None = None
    text: str = ""


class MessageAttachment(BaseModel):
    id: str
    path: str
    media_type: str
    byte_size: int
    content_hash: str
    untrusted: bool = True
    exists: bool = True


class Message(BaseModel):
    id: str
    conversation_id: str
    role: Literal["system", "user", "assistant"]
    content: str
    thinking: str | None
    status: MessageStatus
    error: str | None
    provider_id: str | None
    model_id: str | None
    model_digest: str | None
    metrics: dict[str, Any] | None
    sources: list[MessageSource] = Field(default_factory=list)
    attachments: list[MessageAttachment] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    model_id: str = Field(min_length=1, max_length=200)
    think: bool = False
    boost: bool = False
    image_path: str | None = Field(default=None, max_length=500)


class CompareRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=50_000)
    model_id: str = Field(min_length=1, max_length=200)
    think: bool = False


class AppSettings(BaseModel):
    default_model: str | None = None
    system_prompt: str = (
        "Sen Ahirena'sın; kullanıcının bilgisayarında yerel çalışan kişisel bir asistansın. "
        "Kullanıcı başka bir dil istemedikçe Türkçe yanıt ver. Bilmediğin konuda tahmin yürütüyorsan bunu açıkça söyle."
    )
    context_length: int = Field(default=8192, ge=1024, le=262_144)
    theme: Theme = "system"


class AppSettingsUpdate(BaseModel):
    default_model: str | None = None
    system_prompt: str | None = Field(default=None, max_length=20_000)
    context_length: int | None = Field(default=None, ge=1024, le=262_144)
    theme: Theme | None = None
