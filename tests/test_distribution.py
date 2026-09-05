from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

import onshape_agent
from onshape_agent.contracts import ApprovalStatus, ArtifactType
from onshape_agent.runlog import RunLog

PLUGIN_NAME = "onshape-engineering-agent"
PLUGIN_VERSION = "1.11.1"
REPOSITORY = "https://github.com/2007ryd-hash/onshape-ai-agent"
SKILL_NAME = "onshape-engineering"
SKILL_ROOT_PARTS = (
    "plugins",
    PLUGIN_NAME,
    "skills",
    SKILL_NAME,
)
AGENT_OUTPUTS = {
    "engineering-agent": ("engineering_model.json", "analysis_result.json"),
    "cad-agent": ("cad_spec.json", "execution_plan.json"),
    "drawing-agent": ("drawing_plan.json",),
    "visual-qa-agent": ("visual_report.json",),
}


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def package_version() -> str:
    return tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )["project"]["version"]


def module_version() -> str:
    return onshape_agent.__version__


def plugin_versions(repo_root: Path) -> list[str]:
    manifest_paths = [
        repo_root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json",
        repo_root / "plugins" / PLUGIN_NAME / ".claude-plugin" / "plugin.json",
    ]
    codex_marketplace = load_json(
        repo_root / ".agents" / "plugins" / "marketplace.json"
    )
    claude_marketplace = load_json(repo_root / ".claude-plugin" / "marketplace.json")
    codex_entry = codex_marketplace["plugins"][0]
    claude_entry = claude_marketplace["plugins"][0]
    versions = [load_json(path)["version"] for path in manifest_paths]
    versions.extend(
        [codex_entry["version"], claude_entry["version"]]
    )
    return versions


def test_host_manifests_identify_same_plugin(repo_root: Path) -> None:
    codex = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json"
    )
    claude = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".claude-plugin" / "plugin.json"
    )

    assert codex["name"] == claude["name"] == PLUGIN_NAME
    assert codex["version"] == claude["version"] == PLUGIN_VERSION


def test_python_package_version_matches_plugin_version(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == PLUGIN_VERSION


def test_all_distribution_versions_are_1_11_0(repo_root: Path) -> None:
    assert package_version() == PLUGIN_VERSION
    assert module_version() == PLUGIN_VERSION
    assert set(plugin_versions(repo_root)) == {PLUGIN_VERSION}


def test_manifests_declare_shared_distribution_metadata(repo_root: Path) -> None:
    codex = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json"
    )
    claude = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".claude-plugin" / "plugin.json"
    )

    for manifest in (codex, claude):
        assert manifest["repository"] == REPOSITORY
        assert manifest["license"] == "Apache-2.0"
        assert manifest["author"]["name"] == "2007ryd-hash"
        assert manifest["skills"] == "./skills/"
        assert not {"mcpServers", "hooks", "apps"}.intersection(manifest)


def test_codex_manifest_has_valid_interface_metadata(repo_root: Path) -> None:
    codex = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json"
    )
    interface = codex["interface"]

    assert interface["displayName"] == "Onshape Engineering Agent"
    assert interface["developerName"] == "2007ryd-hash"
    assert interface["category"] == "Developer Tools"
    assert interface["capabilities"]
    assert interface["defaultPrompt"]


def test_marketplaces_reference_canonical_bundle(repo_root: Path) -> None:
    codex = load_json(repo_root / ".agents" / "plugins" / "marketplace.json")
    claude = load_json(repo_root / ".claude-plugin" / "marketplace.json")

    codex_plugin = codex["plugins"][0]
    claude_plugin = claude["plugins"][0]

    assert codex_plugin["name"] == claude_plugin["name"] == PLUGIN_NAME
    assert codex_plugin["source"]["path"] == "./plugins/onshape-engineering-agent"
    assert claude_plugin["source"] == "./plugins/onshape-engineering-agent"
    assert codex_plugin["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert codex_plugin["category"] == "Developer Tools"


def test_license_is_apache_2(repo_root: Path) -> None:
    license_text = (repo_root / "LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("                                Apache License")
    assert "Version 2.0, January 2004" in license_text
    assert "http://www.apache.org/licenses/" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text


def skill_root(repo_root: Path) -> Path:
    return repo_root.joinpath(*SKILL_ROOT_PARTS)


def read_yaml_frontmatter(path: Path) -> tuple[dict, str]:
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)

    assert match is not None
    frontmatter = yaml.safe_load(match.group(1))
    assert isinstance(frontmatter, dict)
    return frontmatter, content[match.end() :]


def extract_section(body: str, heading: str) -> str:
    pattern = rf"(?is)^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s|\Z)"
    match = re.search(pattern, body, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_shared_skill_has_parsed_frontmatter_and_task_dependent_workflows(
    repo_root: Path,
) -> None:
    skill_path = skill_root(repo_root) / "SKILL.md"
    frontmatter, body = read_yaml_frontmatter(skill_path)
    lower_body = body.lower()

    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"] == SKILL_NAME
    assert isinstance(frontmatter["description"], str)
    assert frontmatter["description"].strip()

    workflow_rows = {
        task_type: stages.lower()
        for task_type, stages in re.findall(
            r"(?im)^\|\s*`([^`]+)`\s*\|\s*([^|]+)\|", body
        )
    }
    required_stages = {
        "analysis-only": (
            "intake",
            "requirement artifact",
            "main review",
            "analysis",
            "verification",
            "final review",
        ),
        "cad-edit": (
            "intake",
            "requirement artifact",
            "main review",
            "cad execution plan",
            "onshape-agent",
            "visual qa",
            "verification",
            "final review",
        ),
        "drawing-only": (
            "intake",
            "requirement artifact",
            "main review",
            "drawing plan",
            "onshape-agent",
            "visual qa",
            "verification",
            "final review",
        ),
        "full-design": (
            "intake",
            "requirement artifact",
            "main review",
            "analysis",
            "cad execution plan",
            "onshape-agent",
            "drawing plan",
            "visual qa",
            "verification",
            "final review",
        ),
    }
    for task_type, stages in required_stages.items():
        assert task_type in workflow_rows
        positions = [workflow_rows[task_type].index(stage) for stage in stages]
        assert positions == sorted(positions)
    assert "drawing plan" not in workflow_rows["analysis-only"]
    assert "drawing plan" not in workflow_rows["cad-edit"]
    assert "cad execution plan" not in workflow_rows["drawing-only"]
    assert "visual qa" not in workflow_rows["analysis-only"]
    assert "task-dependent" in lower_body
    assert "only the full-design path" in lower_body
    assert "artifact-only" in lower_body
    assert "json is authoritative" in lower_body
    reference_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", body)
    reference_target = "references/artifact-contracts.md"
    assert reference_target in reference_links
    assert (skill_path.parent / reference_target).is_file()
    for marker in ("UNKNOWN", "NEEDS_CONFIRMATION", "ASSUMPTION"):
        assert f"`{marker}`" in body
    assert "`onshape-agent`" in body
    assert "`simulated`" in body
    assert "`live`" in body
    assert "worker" in lower_body and "onshape" in lower_body
    assert "TODO" not in skill_path.read_text(encoding="utf-8")


def test_openai_metadata_allows_normal_implicit_invocation(repo_root: Path) -> None:
    metadata_path = skill_root(repo_root) / "agents" / "openai.yaml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))

    assert isinstance(metadata, dict)
    assert metadata["policy"]["allow_implicit_invocation"] is True
    assert metadata["interface"]["display_name"] == "Onshape Engineering"
    assert metadata["interface"]["short_description"]
    assert metadata["interface"]["default_prompt"]


def test_artifact_reference_defines_authoritative_contract_boundary(
    repo_root: Path,
) -> None:
    reference_path = skill_root(repo_root) / "references" / "artifact-contracts.md"
    content = reference_path.read_text(encoding="utf-8")
    lower_content = content.lower()

    for output_names in AGENT_OUTPUTS.values():
        for output_name in output_names:
            assert output_name in content
    for status in ("KNOWN", "ASSUMPTION", "UNKNOWN", "NEEDS_CONFIRMATION"):
        assert f"`{status}`" in content
    assert "json" in lower_content
    assert "authoritative" in lower_content
    assert "approval" in lower_content
    assert "content_hash" in content
    assert "input_hashes" in content
    assert "simulated" in lower_content
    assert "live" in lower_content


def test_artifact_reference_matches_runlog_metadata_and_payload_versioning(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    reference_path = skill_root(repo_root) / "references" / "artifact-contracts.md"
    content = reference_path.read_text(encoding="utf-8")
    json_blocks = re.findall(r"(?is)```json\s*(.*?)\s*```", content)

    assert json_blocks
    declared_metadata = json.loads(json_blocks[0])
    declared_fields = {
        "artifact_id",
        "artifact_type",
        "run_id",
        "producer",
        "created_at",
        "input_hashes",
        "content_hash",
        "approval_status",
    }
    assert set(declared_metadata) == declared_fields

    log = RunLog(tmp_path, run_id="run_contract")
    payload = {"semantic_id": "base_plate", "diameter_mm": 8}
    reference = log.write_artifact(
        artifact_id="cad_spec_v1",
        artifact_type=ArtifactType.CAD_SPEC,
        producer="cad_agent",
        payload=payload,
        approval_status=ApprovalStatus.APPROVED,
        input_hashes=["sha256:input"],
    )
    artifact_path = log.artifacts_dir / "cad_spec_v1.json"
    document = json.loads(artifact_path.read_text(encoding="utf-8"))
    metadata = document["metadata"]

    assert set(metadata) == declared_fields
    assert set(metadata) == set(reference.model_dump(mode="json"))
    assert metadata["artifact_id"] == "cad_spec_v1"
    assert metadata["artifact_type"] == "cad_spec"
    assert metadata["run_id"] == "run_contract"
    assert metadata["producer"] == "cad_agent"
    assert metadata["created_at"]
    assert metadata["input_hashes"] == ["sha256:input"]
    assert metadata["content_hash"].startswith("sha256:")
    assert metadata["approval_status"] == "APPROVED"
    assert document["payload"] == payload
    assert "schema_version" not in metadata
    normalized = re.sub(r"\s+", " ", content.lower())
    assert re.search(r"payload.{0,100}schema_version", normalized)
    assert re.search(r"metadata.{0,100}schema_version", normalized)
    assert re.search(
        r"(?:metadata.{0,30}(?:not|never)|(?:not|never).{0,30}metadata)",
        normalized,
    )


def test_specialist_contracts_have_unique_names_and_exact_json_outputs(
    repo_root: Path,
) -> None:
    agents_root = repo_root / "plugins" / PLUGIN_NAME / "agents"
    discovered_names: list[str] = []
    discovered_outputs: list[str] = []

    for agent_name, output_names in AGENT_OUTPUTS.items():
        content_path = agents_root / f"{agent_name}.md"
        frontmatter, body = read_yaml_frontmatter(content_path)
        lower_body = body.lower()
        outputs_section = extract_section(body, "Exact outputs")
        prohibited_section = extract_section(body, "Prohibited actions")
        extracted_outputs = tuple(
            re.findall(r"`([a-z0-9_-]+\.json)`", outputs_section)
        )

        discovered_names.append(frontmatter["name"])
        discovered_outputs.extend(extracted_outputs)
        assert frontmatter["name"] == agent_name
        assert isinstance(frontmatter.get("description"), str)
        assert extracted_outputs == output_names
        assert all(output.endswith(".json") for output in extracted_outputs)
        assert "allowed inputs" in lower_body
        assert "produce only" in lower_body
        assert "json" in lower_body
        assert re.search(
            r"\b(?:do not|must not|never)\b[^\n.]*markdown",
            prohibited_section,
            re.IGNORECASE,
        )
        assert re.search(
            r"\b(?:do not|must not|never)\b[^\n.]*onshape",
            prohibited_section,
            re.IGNORECASE,
        )
        assert "main host agent" in lower_body
        assert "approval" in lower_body
        assert "repair routing" in lower_body
        assert "only the main host agent" in lower_body
        assert "explanation" in lower_body
        assert re.search(r"validated\s+json", lower_body)
        assert "TODO" not in content_path.read_text(encoding="utf-8")

    assert len(discovered_names) == len(set(discovered_names)) == len(AGENT_OUTPUTS)
    assert len(discovered_outputs) == len(set(discovered_outputs))
    assert set(discovered_outputs) == {
        output for outputs in AGENT_OUTPUTS.values() for output in outputs
    }
    assert not any(
        re.search(
            r"(?:state|status|manifest|event|log|context|approval|repair)", output
        )
        for output in discovered_outputs
    )
