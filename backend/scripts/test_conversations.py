
import json
import getpass
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"


def request(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            content = response.read().decode("utf-8")
            return response.status, (
                json.loads(content) if content else None
            )

    except urllib.error.HTTPError as error:
        content = error.read().decode("utf-8")
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            result = {"detail": content}

        return error.code, result

    except Exception as error:
        return 0, {"detail": str(error)}


def check(name, passed, details=""):
    print(
        f"[{'PASS' if passed else 'FAIL'}] {name}"
        + (f" - {details}" if details else "")
    )
    return passed


def login():
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")

    status, result = request(
        "POST",
        "/login",
        data={"email": email, "password": password},
    )

    if status != 200 or not result.get("access_token"):
        print("Login failed:", result)
        return None

    return result["access_token"]


def main():
    print("\n========== CONVERSATION E2E TEST ==========\n")

    passed = 0
    failed = 0

    def test(name, condition, details=""):
        nonlocal passed, failed
        if check(name, condition, details):
            passed += 1
        else:
            failed += 1

    # 1. Login
    token = login()

    if not token:
        print("\nCannot continue without authentication.")
        return

    test("User login", True)

    # 2. Current user
    status, user = request("GET", "/users/me", token)

    test(
        "JWT authentication",
        status == 200 and "id" in user,
        str(user),
    )

    if status != 200:
        return

    user_id = user["id"]

    # 3. Invalid JWT
    status, _ = request(
        "GET",
        "/users/me",
        "invalid.jwt.token",
    )

    test("Invalid JWT rejection", status == 401)

    # 4. Unauthenticated request
    status, _ = request(
        "GET",
        "/conversations",
    )

    test("Unauthenticated request rejection", status == 401)

    # 5. Repository ID
    repository_id = int(
        input("\nEnter your owned repository ID: ")
    )

    # 6. Create conversation
    status, conversation = request(
        "POST",
        "/conversations",
        token,
        {
            "repository_id": repository_id,
            "title": "Automated E2E Test",
        },
    )

    test(
        "Conversation creation",
        status == 201 and "id" in conversation,
        str(conversation),
    )

    if status != 201:
        print("\nCannot continue without a conversation.")
        print("Check repository ownership and repository ID.")
        return

    conversation_id = conversation["id"]

    # 7. Conversation list
    status, conversations = request(
        "GET",
        "/conversations",
        token,
    )

    test(
        "Conversation listing",
        status == 200
        and any(c["id"] == conversation_id for c in conversations),
    )

    # 8. Send real RAG message
    print("\nSending a real RAG question...")

    status, turn = request(
        "POST",
        f"/conversations/{conversation_id}/messages",
        token,
        {
            "content": "Where is JWT authentication implemented?"
        },
    )

    message_success = (
        status == 200
        and "user_message" in turn
        and "assistant_message" in turn
    )

    test(
        "Real message sending and AI response",
        message_success,
        str(turn)[:1000],
    )

    # 9. Conversation history
    status, history = request(
        "GET",
        f"/conversations/{conversation_id}",
        token,
    )

    history_success = (
        status == 200
        and history.get("id") == conversation_id
        and isinstance(history.get("messages"), list)
    )

    test(
        "Conversation history retrieval",
        history_success,
        f"Messages: {len(history.get('messages', []))}"
        if history_success else str(history),
    )

    if history_success and message_success:
        messages = history["messages"]

        test(
            "User message persisted",
            any(m["role"] == "user" for m in messages),
        )

        test(
            "Assistant response persisted",
            any(m["role"] == "assistant" for m in messages),
        )

    # 10. Second user isolation (optional)
    print("\n--- User isolation test ---")
    second_email = input(
        "Second user email (press Enter to skip): "
    ).strip()

    if second_email:
        second_password = getpass.getpass(
            "Second user password: "
        )

        status, second_login = request(
            "POST",
            "/login",
            data={
                "email": second_email,
                "password": second_password,
            },
        )

        if status == 200:
            second_token = second_login["access_token"]

            status, _ = request(
                "GET",
                f"/conversations/{conversation_id}",
                second_token,
            )

            test(
                "Cross-user conversation access blocked",
                status == 404,
                f"HTTP {status}",
            )

            status, second_list = request(
                "GET",
                "/conversations",
                second_token,
            )

            test(
                "Conversation list user isolation",
                status == 200
                and all(
                    c["id"] != conversation_id
                    for c in second_list
                ),
            )
        else:
            test("Second user login", False, str(second_login))
    else:
        print("[SKIP] Cross-user isolation - no second user")

    # Final report
    print("\n========== FINAL REPORT ==========")
    print("Passed:", passed)
    print("Failed:", failed)
    print("Total:", passed + failed)

    if failed == 0:
        print("\nALL EXECUTED TESTS PASSED")
    else:
        print("\nSOME TESTS FAILED - CHECK DETAILS ABOVE")

    print("\nConversation ID:", conversation_id)
    print("User ID:", user_id)


if __name__ == "__main__":
    main()
