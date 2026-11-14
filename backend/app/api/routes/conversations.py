
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Response,
)
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_db,
    get_current_user_id,
    resolve_user_id,
)

from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationResponse,
    ConversationSummaryResponse,
    ConversationDetailResponse,
    MessageCreateRequest,
    ConversationTurnResponse,
)

from app.services.conversation_service import (
    create_user_conversation,
    get_user_conversation_history,
    get_user_conversation_list,
    send_conversation_message,
    delete_user_conversation,
)


router = APIRouter(
    prefix="/conversations",
    tags=["Conversations"],
)


def get_authenticated_user_id(
    current_user_id: int,
) -> int:

    return resolve_user_id(current_user_id)


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation_endpoint(
    request: ConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    user_id = get_authenticated_user_id(current_user_id)

    try:
        return create_user_conversation(
            db=db,
            user_id=user_id,
            repository_id=request.repository_id,
            title=request.title,
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[ConversationSummaryResponse],
)
def list_conversations_endpoint(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    user_id = get_authenticated_user_id(current_user_id)

    return get_user_conversation_list(
        db=db,
        user_id=user_id,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation_history_endpoint(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    user_id = get_authenticated_user_id(current_user_id)

    try:
        conversation, messages = get_user_conversation_history(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        return {
            "id": conversation.id,
            "user_id": conversation.user_id,
            "repository_id": conversation.repository_id,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "messages": messages,
        }

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationTurnResponse,
)
async def send_message_endpoint(
    conversation_id: int,
    request: MessageCreateRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    user_id = get_authenticated_user_id(current_user_id)

    try:
        user_message, assistant_message = (
            await send_conversation_message(
                db=db,
                user_id=user_id,
                conversation_id=conversation_id,
                content=request.content,
            )
        )

        return {
            "conversation_id": conversation_id,
            "user_message": user_message,
            "assistant_message": assistant_message,
        }

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation_endpoint(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    user_id = get_authenticated_user_id(current_user_id)

    try:
        delete_user_conversation(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        return Response(
            status_code=status.HTTP_204_NO_CONTENT
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
