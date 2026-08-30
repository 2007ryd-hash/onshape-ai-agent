from __future__ import annotations

import json

import pytest

from onshape_agent.contracts import ApprovalStatus, ArtifactType, RunState
from onshape_agent.runlog import RunLog


def test_events_are_appended_instead_of_overwritten(tmp_path) -> None:
    log = RunLog(tmp_path, run_id="run_1")

    log.append_event(actor="main", stage=RunState.INTAKE, event="RUN_STARTED")
    log.append_event(actor="cad_gateway", stage=RunState.CAD_EXECUTION, event="DENIED")

    lines = log.events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "RUN_STARTED"
    assert json.loads(lines[1])["event"] == "DENIED"


def test_sensitive_values_are_redacted_recursively(tmp_path) -> None:
    log = RunLog(tmp_path, run_id="run_1")

    log.append_event(
        actor="gateway",
        stage=RunState.CAD_EXECUTION,
        event="AUTH_CHECK",
        details={
            "client_secret": "real-secret",
            "nested": {"access_token": "real-token", "safe": "visible"},
        },
    )

    event = json.loads(log.events_path.read_text(encoding="utf-8"))
    assert event["details"]["client_secret"] == "[REDACTED]"
    assert event["details"]["nested"]["access_token"] == "[REDACTED]"
    assert event["details"]["nested"]["safe"] == "visible"


def test_artifacts_are_immutable_and_content_hashed(tmp_path) -> None:
    log = RunLog(tmp_path, run_id="run_1")
    payload = {"semantic_id": "base_plate", "diameter_mm": 8}

    reference = log.write_artifact(
        artifact_id="cad_spec_v1",
        artifact_type=ArtifactType.CAD_SPEC,
        producer="main_orchestrator",
        payload=payload,
        approval_status=ApprovalStatus.APPROVED,
    )

    assert reference.content_hash.startswith("sha256:")
    assert (log.artifacts_dir / "cad_spec_v1.json").exists()
    with pytest.raises(FileExistsError):
        log.write_artifact(
            artifact_id="cad_spec_v1",
            artifact_type=ArtifactType.CAD_SPEC,
            producer="main_orchestrator",
            payload=payload,
            approval_status=ApprovalStatus.APPROVED,
        )


def test_manifest_records_run_and_main_model_profile(tmp_path) -> None:
    log = RunLog(tmp_path, run_id="run_1")
    manifest = log.create_manifest(main_model="gpt-5.6-sol", reasoning_effort="max")

    assert manifest["run_id"] == "run_1"
    assert manifest["main_model"] == "gpt-5.6-sol"
    assert log.manifest_path.exists()
