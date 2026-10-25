def get_app_name() -> str:
    return "RepoPilot AI"

from app.db.session import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
