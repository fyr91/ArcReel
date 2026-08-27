"""Croco durable job observation behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lib.croco_shared import CrocoClient

pytestmark = pytest.mark.unit


async def test_wait_until_terminal_survives_transient_status_connection_failure(monkeypatch) -> None:
    client = object.__new__(CrocoClient)
    client.get_job = AsyncMock(
        side_effect=[
            httpx.ConnectError("temporary outage"),
            {"status": "succeeded", "stage": "completed", "progress": 100},
        ]
    )
    client.get_queue_position = AsyncMock(return_value=None)
    sleep = AsyncMock()
    monkeypatch.setattr("lib.croco_shared.asyncio.sleep", sleep)

    result = await client.wait_until_terminal("durable-job", max_wait_seconds=60)

    assert result["status"] == "succeeded"
    assert client.get_job.await_count == 2
    sleep.assert_awaited_once_with(5.0)


async def test_wait_until_terminal_surfaces_permanent_status_error(monkeypatch) -> None:
    request = httpx.Request("GET", "https://croco.example/api/v2/jobs/job")
    response = httpx.Response(401, request=request)
    client = object.__new__(CrocoClient)
    client.get_job = AsyncMock(side_effect=httpx.HTTPStatusError("unauthorized", request=request, response=response))
    sleep = AsyncMock()
    monkeypatch.setattr("lib.croco_shared.asyncio.sleep", sleep)

    with pytest.raises(httpx.HTTPStatusError):
        await client.wait_until_terminal("job", max_wait_seconds=60)

    sleep.assert_not_awaited()


async def test_refine_job_posts_without_body_and_uses_explicit_idempotency_key() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"job_id": "child-job"}
    http = AsyncMock()
    http.post = AsyncMock(return_value=response)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)

    with patch("lib.croco_shared.httpx.AsyncClient", return_value=http):
        client = CrocoClient(token="token", base_url="https://croco.example")
        result = await client.refine_job("preview-job", idempotency_key="task-123")

    assert result["job_id"] == "child-job"
    http.post.assert_awaited_once_with(
        "https://croco.example/api/v2/jobs/preview-job/refine",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "task-123"},
    )
