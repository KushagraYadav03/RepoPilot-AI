import getpass
from fastapi.testclient import TestClient
from app.main import app

email = input("Enter email: ")
password = getpass.getpass("Enter password: ")

with TestClient(app) as client:
    response = client.post(
        "/login",
        json={"email": email, "password": password}
    )

    print("\nLOGIN STATUS:", response.status_code)

    if response.status_code == 200:
        token = response.json()["access_token"]
        print("JWT TOKEN GENERATED:", bool(token))

        me = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        print("PROFILE STATUS:", me.status_code)

        if me.status_code == 200:
            print("USER DETAILS:", me.json())
        else:
            print("PROFILE ERROR:", me.text)
    else:
        print("LOGIN ERROR:", response.text)
