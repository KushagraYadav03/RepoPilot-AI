
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateRequest(BaseModel):

    repository_id: int = Field(
        gt=0,
        description="Repository associated with this conversation",
    )

    title: str = Field(
        default="New conversation",
        min_length=1,
        max_length=200,
    )


class MessageCreateRequest(BaseModel):

    content: str = Field(
        min_length=1,
        max_length=10000,
    )


class MessageResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: Literal["user", "assistant"]
    content: str
    provider: str | None = None
    model: str | None = None
    sources: list[dict] | None = None
    created_at: datetime


class ConversationResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    repository_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationSummaryResponse(ConversationResponse):

    message_count: int


class ConversationDetailResponse(ConversationResponse):

    messages: list[MessageResponse]


class ConversationTurnResponse(BaseModel):

    conversation_id: int
    user_message: MessageResponse
    assistant_message: MessageResponse
