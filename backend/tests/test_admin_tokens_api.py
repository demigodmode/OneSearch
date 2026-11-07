# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import pytest

from app.api import auth as auth_module


@pytest.fixture(autouse=True)
def clear_rate_limit():
    auth_module.rate_limit_store.clear()
    yield
    auth_module.rate_limit_store.clear()


@pytest.fixture
def search_stub(monkeypatch):
    async def search(**_kwargs):
        return {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 1}

    monkeypatch.setattr("app.api.search.meili_service.search", search)


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_token(client, name="laptop"):
    response = client.post("/api/auth/tokens", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _search(client, token: str):
    return client.post("/api/search", json={"q": "invoice"}, headers=_as(token))


def _list(client, user_id: int):
    return client.get(f"/api/users/{user_id}/tokens")


def test_admin_lists_only_that_users_tokens_with_status_and_no_secrets(client, member_user, member_client):
    _create_token(client, name="admin laptop")
    created = _create_token(member_client, name="member laptop")
    revoked = _create_token(member_client, name="old laptop")
    assert client.delete(f"/api/users/{member_user.id}/tokens/{revoked['id']}").status_code == 204

    response = _list(client, member_user.id)

    assert response.status_code == 200
    rows = response.json()
    assert [(row["name"], row["status"]) for row in rows] == [("old laptop", "revoked"), ("member laptop", "active")]
    assert rows == member_client.get("/api/auth/tokens").json()
    assert rows[1]["id"] == created["id"]
    assert rows[0]["revoked_at"] is not None
    assert "token" not in rows[0]
    assert created["token"] not in response.text


def test_admin_list_for_unknown_user_is_404(client):
    response = client.get("/api/users/9999/tokens")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_admin_revokes_a_members_token_and_it_gets_401(client, member_user, member_client, search_stub):
    created = _create_token(member_client)
    assert _search(member_client, created["token"]).status_code == 200

    revoke = client.delete(f"/api/users/{member_user.id}/tokens/{created['id']}")

    assert revoke.status_code == 204
    response = _search(member_client, created["token"])
    assert response.status_code == 401
    assert response.json()["detail"] == "API token revoked"
    assert [row["status"] for row in _list(client, member_user.id).json()] == ["revoked"]


def test_revoke_with_the_wrong_user_is_404_and_leaves_the_token_alone(
    client, test_user, member_client, search_stub
):
    created = _create_token(member_client)

    response = client.delete(f"/api/users/{test_user['user'].id}/tokens/{created['id']}")

    assert response.status_code == 404
    assert response.json()["detail"] == "API token not found"
    assert _search(member_client, created["token"]).status_code == 200


def test_revoking_twice_or_an_unknown_token_is_404(client, member_user, member_client):
    created = _create_token(member_client)
    path = f"/api/users/{member_user.id}/tokens/{created['id']}"

    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 404
    assert client.delete(f"/api/users/{member_user.id}/tokens/9999").status_code == 404


def test_admin_revoke_does_not_touch_the_admins_own_tokens(client, member_user, member_client, search_stub):
    own = _create_token(client, name="admin laptop")
    member = _create_token(member_client)

    client.delete(f"/api/users/{member_user.id}/tokens/{own['id']}")

    assert _search(client, own["token"]).status_code == 200
    assert _search(member_client, member["token"]).status_code == 200


def test_disabled_owner_tokens_fail_and_work_again_after_enable(
    client, member_user, member_client, search_stub
):
    created = _create_token(member_client)

    client.patch(f"/api/users/{member_user.id}", json={"is_active": False})
    assert _search(client, created["token"]).status_code == 401

    client.patch(f"/api/users/{member_user.id}", json={"is_active": True})
    assert _search(client, created["token"]).status_code == 200


def test_token_revoked_while_disabled_stays_dead_after_enable(
    client, member_user, member_client, search_stub
):
    created = _create_token(member_client)
    client.patch(f"/api/users/{member_user.id}", json={"is_active": False})
    assert client.delete(f"/api/users/{member_user.id}/tokens/{created['id']}").status_code == 204

    client.patch(f"/api/users/{member_user.id}", json={"is_active": True})

    response = _search(client, created["token"])
    assert response.status_code == 401
    assert response.json()["detail"] == "API token revoked"


def test_demoted_owner_tokens_keep_searching(client, member_user, search_stub):
    client.patch(f"/api/users/{member_user.id}", json={"role": "admin"})
    admin_session = client.post(
        "/api/auth/login", json={"username": "member", "password": "memberpass"}
    ).json()["access_token"]
    created = client.post(
        "/api/auth/tokens", json={"name": "scripts"}, headers=_as(admin_session)
    ).json()

    demoted = client.patch(f"/api/users/{member_user.id}", json={"role": "member"})

    assert demoted.status_code == 200
    assert _search(client, created["token"]).status_code == 200


def test_members_get_403_for_admin_token_routes(client, member_user, member_client):
    created = _create_token(member_client)

    assert member_client.get(f"/api/users/{member_user.id}/tokens").status_code == 403
    revoke = member_client.delete(f"/api/users/{member_user.id}/tokens/{created['id']}")

    assert revoke.status_code == 403
    assert _list(client, member_user.id).json()[0]["id"] == created["id"]
