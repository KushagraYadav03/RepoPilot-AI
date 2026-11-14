
from sqlalchemy.orm import Session

from app.repositories.conversation_repository import (
    get_owned_repository,
    count_user_conversations,
    create_conversation,
    get_owned_conversation,
    list_user_conversations,
    count_conversation_messages,
    create_message,
    get_conversation_messages,
    delete_conversation,
)

from app.services.rag_service import answer_repository_question


MAX_CONVERSATIONS_PER_USER = 50
MAX_MESSAGES_PER_CONVERSATION = 100
MAX_MESSAGE_LENGTH = 10000


def create_user_conversation(
    db: Session,
    user_id: int,
    repository_id: int,
    title: str,
):

    repository = get_owned_repository(
        db,
        repository_id,
        user_id,
    )

    if repository is None:
        raise LookupError("Repository not found")

    conversation_count = count_user_conversations(
        db,
        user_id,
    )

    if conversation_count >= MAX_CONVERSATIONS_PER_USER:
        raise ValueError(
            "Maximum conversation limit reached"
        )

    return create_conversation(
        db=db,
        user_id=user_id,
        repository_id=repository_id,
        title=title.strip(),
    )


def get_user_conversation(
    db: Session,
    user_id: int,
    conversation_id: int,
):

    conversation = get_owned_conversation(
        db,
        conversation_id,
        user_id,
    )

    if conversation is None:
        raise LookupError("Conversation not found")

    return conversation


def get_user_conversation_history(
    db: Session,
    user_id: int,
    conversation_id: int,
):

    conversation = get_user_conversation(
        db,
        user_id,
        conversation_id,
    )

    messages = get_conversation_messages(
        db,
        conversation.id,
    )

    return conversation, messages


def get_user_conversation_list(
    db: Session,
    user_id: int,
):

    conversations = list_user_conversations(
        db,
        user_id,
    )

    results = []

    for conversation in conversations:

        message_count = count_conversation_messages(
            db,
            conversation.id,
        )

        results.append(
            {
                "id": conversation.id,
                "user_id": conversation.user_id,
                "repository_id": conversation.repository_id,
                "title": conversation.title,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
                "message_count": message_count,
            }
        )

    return results


async def send_conversation_message(
    db: Session,
    user_id: int,
    conversation_id: int,
    content: str,
):

    content = content.strip()

    if not content:
        raise ValueError("Message cannot be empty")

    if len(content) > MAX_MESSAGE_LENGTH:
        raise ValueError("Message is too long")

    conversation = get_user_conversation(
        db,
        user_id,
        conversation_id,
    )

    message_count = count_conversation_messages(
        db,
        conversation_id,
    )

    # Two slots are required:
    # one for the user and one for the assistant.

    if message_count + 2 > MAX_MESSAGES_PER_CONVERSATION:
        raise ValueError(
            "Maximum message limit reached for this conversation"
        )

    # Store the user message first.

    user_message = create_message(
        db=db,
        conversation_id=conversation_id,
        role="user",
        content=content,
    )

    # Generate the AI response using the existing RAG pipeline.

    result = await answer_repository_question(
        repository_id=conversation.repository_id,
        query=content,
        limit=5,
    )

    # Update conversation title using its first question.

    if conversation.title == "New conversation":
        conversation.title = content[:200]

    # Store the AI response and its citations.

    assistant_message = create_message(
        db=db,
        conversation_id=conversation_id,
        role="assistant",
        content=result["answer"],
        provider=result["provider"],
        model=result["model"],
        sources=result["sources"],
    )

    db.commit()

    db.refresh(conversation)

    return user_message, assistant_message


def delete_user_conversation(
    db: Session,
    user_id: int,
    conversation_id: int,
):

    conversation = get_user_conversation(
        db,
        user_id,
        conversation_id,
    )

    delete_conversation(
        db,
        conversation,
    )
