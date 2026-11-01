from uuid import uuid4

from app.db.session import SessionLocal
from app.repositories.user import (
    create_user,
    get_user_by_email,
)
from app.core.security import hash_password, verify_password

db = SessionLocal()

try:
    email = f"test_{uuid4().hex[:8]}@example.com"

    hashed = hash_password("Kushagra@123")

    user = create_user(
        db,
        "Kushagra",
        email,
        hashed
    )

    print("User created:", user.id)

    found_user = get_user_by_email(db, email)

    print("User found:", found_user is not None)
    print("Name:", found_user.name)
    print("Password verified:", verify_password(
        "Kushagra@123",
        found_user.hashed_password
    ))

finally:
    db.close()