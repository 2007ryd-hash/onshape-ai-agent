from __future__ import annotations

import json
from pathlib import Path

import pytest


PLUGIN_NAME = "onshape-engineering-agent"
PLUGIN_VERSION = "0.2.0"
REPOSITORY = "https://github.com/2007ryd-hash/onshape-ai-agent"


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
