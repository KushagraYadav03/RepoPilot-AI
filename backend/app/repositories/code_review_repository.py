from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.code_review import CodeReview


def create_code_review(
    db: Session,
    user_id: int,
    repository_id: int,
    diff_type: str,
    identifier: str,
    title: str | None,
    review_data: dict,
) -> CodeReview:

    review = CodeReview(
        user_id=user_id,
        repository_id=repository_id,
        diff_type=diff_type,
        identifier=identifier,
        title=title,
        review_data=review_data,
    )

    try:
        db.add(review)
        db.commit()
        db.refresh(review)

        return review

    except Exception:
        db.rollback()
        raise


def get_code_review_by_id(
    db: Session,
    review_id: int,
    user_id: int,
) -> CodeReview | None:

    statement = select(CodeReview).where(
        CodeReview.id == review_id,
        CodeReview.user_id == user_id,
    )

    return db.scalar(statement)