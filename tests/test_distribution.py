from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_NAME = "onshape-engineering-agent"
PLUGIN_VERSION = "0.2.0"
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


def test_host_manifests_identify_same_plugin(repo_root: Path) -> None:
    codex = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json"
    )
    claude = load_json(
        repo_root / "plugins" / PLUGIN_NAME / ".claude-plugin" / "plugin.json"
    )

    assert codex["name"] == claude["name"] == PLUGIN_NAME
    assert codex["version"] == claude["version"] == PLUGIN_VERSION


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


def test_shared_skill_has_skill_creator_frontmatter_and_workflow(
    repo_root: Path,
) -> None:
    skill_path = skill_root(repo_root) / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    frontmatter_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)

    assert frontmatter_match is not None
    frontmatter = frontmatter_match.group(1)
    frontmatter_keys = {
        line.split(":", 1)[0].strip()
        for line in frontmatter.splitlines()
        if ":" in line
    }
    assert frontmatter_keys == {"name", "description"}
    assert re.search(r"(?m)^name:\s*onshape-engineering\s*$", frontmatter)
    assert re.search(r"(?m)^description:\s*\S", frontmatter)

    body = content[frontmatter_match.end() :]
    lower_body = body.lower()
    workflow = (
        "intake",
        "requirement artifact",
        "main review",
        "cad execution plan",
        "local `onshape-agent` command",
        "drawing plan",
        "verification",
        "final review",
    )
    workflow_body = lower_body[lower_body.index("intake ->") :]
    positions = [workflow_body.index(step) for step in workflow]
    assert positions == sorted(positions)
    assert "artifact-only" in lower_body
    assert "json is authoritative" in lower_body
    assert "references/artifact-contracts.md" in body
    for marker in ("UNKNOWN", "NEEDS_CONFIRMATION", "ASSUMPTION"):
        assert f"`{marker}`" in body
    assert "`onshape-agent`" in body
    assert "`simulated`" in body
    assert "`live`" in body
    assert "worker" in lower_body and "onshape" in lower_body
    assert "TODO" not in content
    assert "[TODO" not in content


def test_openai_metadata_allows_normal_implicit_invocation(repo_root: Path) -> None:
    metadata_path = skill_root(repo_root) / "agents" / "openai.yaml"
    content = metadata_path.read_text(encoding="utf-8")

    assert "interface:" in content
    assert 'display_name: "Onshape Engineering"' in content
    assert "short_description:" in content
    assert "default_prompt:" in content
    assert "policy:" in content
    assert "allow_implicit_invocation: true" in content


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


def test_specialist_contracts_have_unique_names_and_exact_json_outputs(
    repo_root: Path,
) -> None:
    agents_root = repo_root / "plugins" / PLUGIN_NAME / "agents"
    discovered_names: list[str] = []

    for agent_name, output_names in AGENT_OUTPUTS.items():
        content = (agents_root / f"{agent_name}.md").read_text(encoding="utf-8")
        name_match = re.search(r"(?m)^name:\s*([a-z0-9-]+)\s*$", content)

        assert name_match is not None
        discovered_names.append(name_match.group(1))
        assert name_match.group(1) == agent_name
        assert "allowed inputs" in content.lower()
        assert "exact outputs" in content.lower()
        assert "produce only" in content.lower()
        assert "json" in content.lower()
        for output_name in output_names:
            assert f"`{output_name}`" in content
        assert "onshape" in content.lower()
        assert "do not" in content.lower()
        assert "main host agent" in content.lower()
        assert "approve" in content.lower()
        assert "repair routing" in content.lower()
        assert "TODO" not in content

    assert len(discovered_names) == len(set(discovered_names)) == len(AGENT_OUTPUTS)
