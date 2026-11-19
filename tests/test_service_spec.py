from pathlib import Path

import pytest
from pydantic import ValidationError

from homelab_common import load_service_spec
from homelab_common.cli import main
from homelab_common.service_spec import RunSpec

# SPEC section 5, with TASKS_API standing in for the example's env var name.
EXAMPLE = """\
apiVersion: homelab/v1
name: tasks
title: Tasks
description: Boards, reminders and the tasks API
repo: navaneethkrishna30/tasks
run:
  port: 8000
  network: homelab
  env: [TASKS_API]
database: {schema: tasks}
gateway: {path: /tasks}
mcp:
  enabled: true
  path: /mcp
  profiles: [builder]
  tools: ["tasks_*"]
telemetry: {otlp: true}
boot: {heal: true, units: []}
"""

MINIMAL = """\
apiVersion: homelab/v1
name: tasks
title: Tasks
description: Boards, reminders and the tasks API
repo: navaneethkrishna30/tasks
"""


def write_spec(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "service.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_example_parses(tmp_path: Path) -> None:
    spec = load_service_spec(write_spec(tmp_path, EXAMPLE))
    assert spec.name == "tasks"
    assert spec.repo == "navaneethkrishna30/tasks"
    assert spec.run == RunSpec(port=8000, network="homelab", env=["TASKS_API"])
    assert spec.database is not None
    assert spec.database.schema_name == "tasks"
    assert spec.gateway.path == "/tasks"
    assert spec.mcp.enabled is True
    assert spec.mcp.profiles == ["builder"]
    assert spec.mcp.tools == ["tasks_*"]
    assert spec.telemetry.otlp is True
    assert spec.boot.heal is True


def test_defaults_applied(tmp_path: Path) -> None:
    spec = load_service_spec(write_spec(tmp_path, MINIMAL))
    assert spec.run == RunSpec()
    assert spec.database is None
    assert spec.gateway.path == "/tasks"
    assert spec.mcp.enabled is False
    assert spec.mcp.path == "/mcp"
    assert spec.mcp.profiles == []
    assert spec.mcp.tools == ["*"]
    assert spec.telemetry.otlp is True
    assert spec.boot.heal is True
    assert spec.boot.units == []


def test_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_service_spec(write_spec(tmp_path, MINIMAL + "backup: true\n"))


def test_bad_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_service_spec(write_spec(tmp_path, MINIMAL.replace("name: tasks", "name: Tasks")))


def test_gateway_path_needs_leading_slash(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_service_spec(write_spec(tmp_path, MINIMAL + "gateway: {path: tasks}\n"))


def test_bad_env_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_service_spec(write_spec(tmp_path, MINIMAL + "run: {env: [tasks_api]}\n"))


def test_host_network_accepted(tmp_path: Path) -> None:
    spec = load_service_spec(write_spec(tmp_path, MINIMAL + "run: {network: host}\n"))
    assert spec.run.network == "host"


def test_unknown_network_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_service_spec(write_spec(tmp_path, MINIMAL + "run: {network: lan}\n"))


def test_cli_returns_0_for_valid_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(write_spec(tmp_path, MINIMAL))]) == 0
    assert capsys.readouterr().out == "ok: tasks\n"


def test_cli_returns_1_for_invalid_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(write_spec(tmp_path, MINIMAL + "backup: true\n"))]) == 1
    assert capsys.readouterr().err != ""


def test_cli_returns_2_for_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(tmp_path / "absent.yaml")]) == 2
    assert capsys.readouterr().err.count("\n") == 1
