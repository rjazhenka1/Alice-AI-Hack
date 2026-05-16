from __future__ import annotations

import pytest

from app.agent.alice import AlicePlanner, PlannedCommand


@pytest.mark.asyncio
async def test_planner_uses_remote_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALICE_API_KEY", "k")
    monkeypatch.setenv("ALICE_FOLDER_ID", "f")
    monkeypatch.setenv("ALICE_MODEL", "yandexgpt")

    planner = AlicePlanner()

    async def fake_remote(*, text: str, system_prompt: str | None):
        return PlannedCommand(kind="clarification", message="remote", title=None, description=text)

    monkeypatch.setattr(planner, "_plan_remote", fake_remote)

    result = await planner.plan("Нужны люди", system_prompt="policy")
    assert result.kind == "clarification"
    assert result.message == "remote"


@pytest.mark.asyncio
async def test_planner_falls_back_to_local_if_remote_failed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALICE_API_KEY", "k")
    monkeypatch.setenv("ALICE_FOLDER_ID", "f")
    monkeypatch.setenv("ALICE_MODEL", "yandexgpt")

    planner = AlicePlanner()

    async def fake_remote_none(*, text: str, system_prompt: str | None):
        return None

    monkeypatch.setattr(planner, "_plan_remote", fake_remote_none)

    with pytest.raises(RuntimeError) as exc:
        await planner.plan("Ну ты поняла", system_prompt="policy")
    assert "Alice API request failed" in str(exc.value)


@pytest.mark.asyncio
async def test_planner_raises_if_creds_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ALICE_API_KEY", raising=False)
    monkeypatch.delenv("ALICE_FOLDER_ID", raising=False)
    monkeypatch.setenv("ALICE_MODEL", "yandexgpt")
    planner = AlicePlanner()

    with pytest.raises(RuntimeError) as exc:
        await planner.plan("На входе толпа", system_prompt="policy")
    assert "Alice API is not configured" in str(exc.value)
