
from uuid import uuid4

from app.db.session import SessionLocal
from app.models.user import User
from app.models.repository import Repository
from app.models.conversation import Conversation
from app.models.message import Message

from app.repositories.conversation_repository import (
    get_owned_repository,
    create_conversation,
    get_owned_conversation,
    list_user_conversations,
    count_conversation_messages,
    create_message,
    get_conversation_messages,
    delete_conversation,
)


def get_test_user_and_repository(db):

    user = db.get(User, 28)
    repository = db.get(Repository, 1)

    assert user is not None
    assert repository is not None
    assert repository.owner_id == user.id

    return user, repository


def create_test_conversation(db):

    user, repository = get_test_user_and_repository(db)

    conversation = create_conversation(
        db=db,
        user_id=user.id,
        repository_id=repository.id,
        title=f"Test Conversation {uuid4().hex[:8]}",
    )

    return conversation


def cleanup_conversation(db, conversation_id):

    if conversation_id is not None:

        conversation = db.get(
            Conversation,
            conversation_id,
        )

        if conversation is not None:
            delete_conversation(db, conversation)


# ---------------------------------------------------------
# TEST 1: EXISTING COMPLETE CRUD TEST
# ---------------------------------------------------------

def test_conversation_crud():

    db = SessionLocal()
    conversation_id = None

    try:
        user, repository = get_test_user_and_repository(db)

        conversation = Conversation(
            user_id=user.id,
            repository_id=repository.id,
            title="CRUD Test Conversation",
        )

        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        conversation_id = conversation.id

        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content="What is FastAPI?",
        )

        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="FastAPI is a Python web framework.",
        )

        db.add_all([user_message, assistant_message])
        db.commit()

        fetched = db.get(Conversation, conversation_id)

        assert fetched is not None
        assert len(fetched.messages) == 2

        fetched.title = "Updated CRUD Test"
        db.commit()
        db.refresh(fetched)

        assert fetched.title == "Updated CRUD Test"

        db.delete(fetched)
        db.commit()

        assert db.get(Conversation, conversation_id) is None

        remaining_messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .count()
        )

        assert remaining_messages == 0

    finally:
        cleanup_conversation(db, conversation_id)
        db.close()


# ---------------------------------------------------------
# TEST 2: REPOSITORY OWNERSHIP
# ---------------------------------------------------------

def test_repository_ownership():

    db = SessionLocal()

    try:
        user, repository = get_test_user_and_repository(db)

        owned_repository = get_owned_repository(
            db,
            repository.id,
            user.id,
        )

        assert owned_repository is not None
        assert owned_repository.id == repository.id

        unauthorized_repository = get_owned_repository(
            db,
            repository.id,
            999999,
        )

        assert unauthorized_repository is None

    finally:
        db.close()


# ---------------------------------------------------------
# TEST 3: CREATE CONVERSATION
# ---------------------------------------------------------

def test_create_conversation():

    db = SessionLocal()
    conversation_id = None

    try:
        conversation = create_test_conversation(db)
        conversation_id = conversation.id

        assert conversation.id is not None
        assert conversation.user_id == 28
        assert conversation.repository_id == 1
        assert conversation.title.startswith("Test Conversation")

        saved_conversation = db.get(
            Conversation,
            conversation_id,
        )

        assert saved_conversation is not None

    finally:
        cleanup_conversation(db, conversation_id)
        db.close()


# ---------------------------------------------------------
# TEST 4: CONVERSATION OWNERSHIP
# ---------------------------------------------------------

def test_conversation_ownership():

    db = SessionLocal()
    conversation_id = None

    try:
        conversation = create_test_conversation(db)
        conversation_id = conversation.id

        owned_conversation = get_owned_conversation(
            db,
            conversation_id,
            28,
        )

        assert owned_conversation is not None

        unauthorized_conversation = get_owned_conversation(
            db,
            conversation_id,
            999999,
        )

        assert unauthorized_conversation is None

    finally:
        cleanup_conversation(db, conversation_id)
        db.close()


# ---------------------------------------------------------
# TEST 5: USER-WISE CONVERSATION LIST
# ---------------------------------------------------------

def test_list_user_conversations():

    db = SessionLocal()
    conversation_id = None

    try:
        conversation = create_test_conversation(db)
        conversation_id = conversation.id

        conversations = list_user_conversations(
            db,
            28,
        )

        conversation_ids = [
            item.id for item in conversations
        ]

        assert conversation_id in conversation_ids

        for item in conversations:
            assert item.user_id == 28

        unauthorized_list = list_user_conversations(
            db,
            999999,
        )

        assert unauthorized_list == []

    finally:
        cleanup_conversation(db, conversation_id)
        db.close()


# ---------------------------------------------------------
# TEST 6: MESSAGE CREATION, COUNT AND ORDERING
# ---------------------------------------------------------

def test_message_creation_and_history():

    db = SessionLocal()
    conversation_id = None

    try:
        conversation = create_test_conversation(db)
        conversation_id = conversation.id

        create_message(
            db=db,
            conversation_id=conversation_id,
            role="user",
            content="What is FastAPI?",
        )

        create_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content="FastAPI is a Python web framework.",
        )

        message_count = count_conversation_messages(
            db,
            conversation_id,
        )

        assert message_count == 2

        messages = get_conversation_messages(
            db,
            conversation_id,
        )

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

        assert messages[0].content == "What is FastAPI?"
        assert messages[1].content == (
            "FastAPI is a Python web framework."
        )

    finally:
        cleanup_conversation(db, conversation_id)
        db.close()


# ---------------------------------------------------------
# TEST 7: DELETE CONVERSATION AND CASCADE DELETE
# ---------------------------------------------------------

def test_delete_conversation_cascade():

    db = SessionLocal()
    conversation_id = None

    try:
        conversation = create_test_conversation(db)
        conversation_id = conversation.id

        create_message(
            db=db,
            conversation_id=conversation_id,
            role="user",
            content="Test deletion",
        )

        create_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content="Test response",
        )

        assert count_conversation_messages(
            db,
            conversation_id,
        ) == 2

        delete_conversation(
            db,
            conversation,
        )

        assert db.get(
            Conversation,
            conversation_id,
        ) is None

        assert count_conversation_messages(
            db,
            conversation_id,
        ) == 0

    finally:
        cleanup_conversation(db, conversation_id)
        db.close()
