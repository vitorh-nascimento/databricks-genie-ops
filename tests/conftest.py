"""Fixtures compartilhadas e mocks da Databricks CLI para a suíte de testes do GenieOps."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from genieops.databricks_client import DatabricksClient
from genieops.loader import load_space
from genieops.models import SpaceBundle

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FakeCompletedProcess:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeCLIRunner:
    """Simula subprocess.run para comandos `databricks ...` de forma determinística."""

    def __init__(self, handler: Callable[[list[str]], FakeCompletedProcess]) -> None:
        self.handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> FakeCompletedProcess:
        self.calls.append(cmd)
        return self.handler(cmd)


def make_json_response(payload: Any, rc: int = 0, stderr: str = "") -> FakeCompletedProcess:
    return FakeCompletedProcess(
        returncode=rc,
        stdout=json.dumps(payload, ensure_ascii=False),
        stderr=stderr,
    )


@pytest.fixture()
def exemplo_bundle() -> SpaceBundle:
    return load_space("exemplo_vendas", base_dir=REPO_ROOT)


@pytest.fixture()
def mock_client_factory():
    def _factory(handler: Callable[[list[str]], FakeCompletedProcess]) -> tuple[DatabricksClient, FakeCLIRunner]:
        runner = FakeCLIRunner(handler)
        client = DatabricksClient(profile="test-profile", warehouse_id="wh_test_01", runner=runner)
        return client, runner

    return _factory
