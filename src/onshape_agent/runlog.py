"""Immutable run artifacts and append-only, redacted event logging."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import ApprovalStatus, ArtifactRef, ArtifactType, RunState

SENSITIVE_KEY_PARTS = ("secret", "token", "password", "authorization")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class RunLog:
    def __init__(self, base_dir: Path, *, run_id: str) -> None:
        self.run_id = run_id
        self.run_dir = Path(base_dir) / run_id
        self.artifacts_dir = self.run_dir / "artifacts"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.manifest_path = self.run_dir / "manifest.json"

    def create_manifest(
        self,
        *,
        main_model: str,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        manifest = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "created_at": _utc_now(),
            "main_model": main_model,
            "reasoning_effort": reasoning_effort,
        }
        _write_json_atomic(self.manifest_path, manifest)
        return manifest

    def append_event(
        self,
        *,
        actor: str,
        stage: RunState,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "schema_version": "1.0",
            "event_id": f"evt_{uuid4().hex}",
            "run_id": self.run_id,
            "timestamp": _utc_now(),
            "actor": actor,
            "stage": stage.value,
            "event": event,
            "details": _redact(details or {}),
        }
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(record) + "\n")
        return record

    def write_artifact(
        self,
        *,
        artifact_id: str,
        artifact_type: ArtifactType,
        producer: str,
        payload: dict[str, Any],
        approval_status: ApprovalStatus = ApprovalStatus.PENDING,
        input_hashes: list[str] | None = None,
    ) -> ArtifactRef:
        path = self.artifacts_dir / f"{artifact_id}.json"
        if path.exists():
            raise FileExistsError(f"artifact already exists: {artifact_id}")

        safe_payload = _redact(payload)
        canonical_payload = _canonical_json(safe_payload).encode("utf-8")
        digest = hashlib.sha256(canonical_payload).hexdigest()
        reference = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            run_id=self.run_id,
            producer=producer,
            input_hashes=input_hashes or [],
            content_hash=f"sha256:{digest}",
            approval_status=approval_status,
        )
        document = {
            "metadata": reference.model_dump(mode="json"),
            "payload": safe_payload,
        }
        _write_json_atomic(path, document)
        return reference
