# -*- coding: utf-8 -*-
"""Meta 集成测试：分页 / 限流退避 / 异常分类 / token 脱敏与加密 / Mock / 幂等同步。"""
from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from crossborder_ops.core import crypto
from crossborder_ops.integrations.meta import build_meta_client
from crossborder_ops.integrations.meta.client import MetaClient
from crossborder_ops.integrations.meta.errors import (MetaAuthError, MetaConfigError,
                                                      MetaNetworkError, MetaPermissionError,
                                                      MetaRateLimited, MetaServerError)
from tests.conftest import auth

# ---------------- 加密 ----------------
def test_token_encrypt_roundtrip_and_mask():
    cipher = crypto.encrypt("EAAG-secret-token")
    assert cipher != "EAAG-secret-token"
    assert crypto.decrypt(cipher) == "EAAG-secret-token"
    assert crypto.mask("EAAG-secret-token") == "EAAG***oken"
    assert crypto.mask("") == ""


# ---------------- 分页 ----------------
async def _collect(client, path, params):
    return [item async for item in client.paginate(path, params)]


async def test_pagination_follows_next():
    pages = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        pages["n"] += 1
        if pages["n"] == 1:
            return httpx.Response(200, json={"data": [{"id": "1"}, {"id": "2"}],
                                             "paging": {"next": "https://graph.test/page2"}})
        return httpx.Response(200, json={"data": [{"id": "3"}], "paging": {}})

    client = MetaClient("tok", transport=httpx.MockTransport(handler))
    items = await _collect(client, "act_1/campaigns", {"limit": 2})
    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert pages["n"] == 2


async def test_pagination_follows_cursor():
    def handler(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        if not after:
            return httpx.Response(200, json={"data": [{"id": "1"}],
                                             "paging": {"cursors": {"after": "c1"}}})
        return httpx.Response(200, json={"data": [{"id": "2"}],
                                         "paging": {"cursors": {}}})

    client = MetaClient("tok", transport=httpx.MockTransport(handler))
    assert [i["id"] for i in await _collect(client, "act_1/ads", {})] == ["1", "2"]


# ---------------- 限流 / 退避 ----------------
async def test_429_retry_after_is_respected(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.25"})
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("crossborder_ops.integrations.meta.client.asyncio.sleep", fake_sleep)
    client = MetaClient("tok", transport=httpx.MockTransport(handler))
    result = await client.get("act_1/campaigns")
    assert result["data"] == []
    assert sleeps == [0.25]
    assert client.stats["throttled"] == 0 and client.stats["retries"] == 1


async def test_429_exhausts_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = MetaClient("tok", max_retries=2, transport=httpx.MockTransport(handler))
    with pytest.raises(MetaRateLimited):
        await client.get("act_1/campaigns")


# ---------------- 异常分类 ----------------
async def _raise_client(status: int, *, retries: int = 0):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": 1, "message": "x"}})

    client = MetaClient("tok", max_retries=retries, transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as exc:
        await client.get("act_1/campaigns")
    return exc.value


async def test_401_is_auth_error():
    assert isinstance(await _raise_client(401), MetaAuthError)


async def test_403_is_permission_error():
    assert isinstance(await _raise_client(403), MetaPermissionError)


async def test_5xx_is_server_error():
    assert isinstance(await _raise_client(500, retries=1), MetaServerError)


async def test_timeout_is_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    client = MetaClient("tok", transport=httpx.MockTransport(handler))
    with pytest.raises(MetaNetworkError):
        await client.get("act_1/campaigns")


async def test_no_token_raises_config_error():
    with pytest.raises(MetaConfigError):
        MetaClient("")


# ---------------- token 不上日志 ----------------
async def test_access_token_not_in_logs(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    token = "EAAG-super-secret-token-value"
    client = MetaClient(token, max_retries=0, transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.WARNING, logger="crossborder_ops.integrations.meta.client"):
        with pytest.raises(MetaRateLimited):
            await client.get("act_1/campaigns")
    assert token not in caplog.text
    assert "***" in caplog.text


# ---------------- Mock ----------------
def test_mock_client_is_explicit():
    client = build_meta_client(None)
    assert client.is_mock is True
    assert client.describe()["mock"] is True


async def test_mock_returns_mock_flag_and_synthetic_rows():
    client = build_meta_client(None)
    payload = await client.get("me/adaccounts")
    assert payload["mock"] is True and payload["source"] == "mock"
    assert len(payload["data"]) == 2


# ---------------- 同步幂等 ----------------
async def test_meta_sync_is_idempotent_and_marked_mock(api, two_shops, sessionmaker_):
    from crossborder_ops.services import meta_sync
    from crossborder_ops.repositories import ads as ads_repo

    client = build_meta_client(None)
    async with sessionmaker_() as session:
        async with session.begin():
            first = await meta_sync.sync_all(session, "S1", client,
                                             since=__import__("datetime").date(2026, 3, 1),
                                             until=__import__("datetime").date(2026, 3, 3))
    async with sessionmaker_() as session:
        async with session.begin():
            second = await meta_sync.sync_all(session, "S1", client,
                                              since=__import__("datetime").date(2026, 3, 1),
                                              until=__import__("datetime").date(2026, 3, 3))
    assert first == second
    assert first["source"] == "mock"
    async with sessionmaker_() as session:
        accounts = await ads_repo.list_accounts(session, "S1")
    # Mock 账户固定 2 个（DB 里可能还有其它测试创建的账户）
    assert first["accounts"] == 2
    assert first["campaigns"] == len(accounts) * 2
    assert first["insights"] == len(accounts) * 3
    async with sessionmaker_() as session:
        rows = await ads_repo.list_insights(session, "S1",
                                            date_from=__import__("datetime").date(2026, 3, 1),
                                            date_to=__import__("datetime").date(2026, 3, 3))
        account_ids = {a.external_id for a in accounts}
        target = [r for r in rows if r.entity_external_id in account_ids]
        assert len(target) == len(accounts) * 3   # 每账户 3 天
        assert {r.source for r in target} == {"mock"}


# ---------------- API ----------------
async def test_meta_api_status_and_sync(api, two_shops):
    status = await api.get("/api/v1/meta/status", headers=auth(two_shops["S1"]))
    assert status.json()["data"]["mock"] is True

    sync = await api.post("/api/v1/meta/sync", headers=auth(two_shops["S1"]),
                          json={"since": "2026-03-01", "until": "2026-03-03"})
    body = sync.json()["data"]
    assert body["source"] == "mock" and body["insights"] > 0

    accounts = await api.get("/api/v1/meta/accounts", headers=auth(two_shops["S1"]))
    assert accounts.json()["data"]["source"] == "mock"
