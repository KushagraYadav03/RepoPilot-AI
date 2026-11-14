
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.repository import Repository


def get_owned_repository(
    db: Session,
    repository_id: int,
    user_id: int,
):
    return db.query(Repository).filter(
        Repository.id == repository_id,
        Repository.owner_id == user_id,
    ).first()


def count_user_conversations(
    db: Session,
    user_id: int,
) -> int:
    return db.query(func.count(Conversation.id)).filter(
        Conversation.user_id == user_id
    ).scalar() or 0


def create_conversation(
    db: Session,
    user_id: int,
    repository_id: int,
    title: str,
) -> Conversation:

    conversation = Conversation(
        user_id=user_id,
        repository_id=repository_id,
        title=title,
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


def get_owned_conversation(
    db: Session,
    conversation_id: int,
    user_id: int,
):
    return db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    ).first()


def list_user_conversations(
    db: Session,
    user_id: int,
):
    return db.query(Conversation).filter(
        Conversation.user_id == user_id
    ).order_by(
        Conversation.updated_at.desc()
    ).all()


def count_conversation_messages(
    db: Session,
    conversation_id: int,
) -> int:
    return db.query(func.count(Message.id)).filter(
        Message.conversation_id == conversation_id
    ).scalar() or 0


def create_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    sources: list[dict] | None = None,
) -> Message:

    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        provider=provider,
        model=model,
        sources=sources,
    )

    db.add(message)

    db.commit()
    db.refresh(message)

    return message


def get_conversation_messages(
    db: Session,
    conversation_id: int,
):
    return db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(
        Message.created_at.asc(),
        Message.id.asc(),
    ).all()


def delete_conversation(
    db: Session,
    conversation: Conversation,
) -> None:

    db.delete(conversation)
    db.commit()
