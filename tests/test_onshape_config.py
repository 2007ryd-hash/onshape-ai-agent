from __future__ import annotations

from pathlib import Path

from tomlkit import parse

from onshape_agent.onshape_config import update_config


def test_update_config_preserves_complex_toml_and_updates_auth(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = (
        "# top-level comment\n"
        'title = "preserve"\n'
        "numbers = [1, 2, 3] # inline comment\n"
        'description = """line one\nline two\n"""\n\n'
        "[auth]\n"
        "# credentials are replaced below\n"
        'provider = "onshape"\n'
        'client_id = "old-id"\n'
        'client_secret = "old-secret"\n'
        'redirect_uri = "old-callback"\n\n'
        "[other]\n"
        "enabled = true\n"
    )
    config_path.write_text(original, encoding="utf-8")

    update_config(
        config_path,
        client_id='id"quoted\\path',
        client_secret='secret"quoted\\path',
        redirect_uri="http://localhost:18338/callback",
    )

    rendered = config_path.read_text(encoding="utf-8")
    parsed = parse(rendered)
    assert parsed["title"] == "preserve"
    assert parsed["numbers"] == [1, 2, 3]
    assert parsed["description"] == "line one\nline two\n"
    assert parsed["auth"]["provider"] == "onshape"
    assert parsed["auth"]["client_id"] == 'id"quoted\\path'
    assert parsed["auth"]["client_secret"] == 'secret"quoted\\path'
    assert parsed["auth"]["redirect_uri"] == "http://localhost:18338/callback"
    assert parsed["other"]["enabled"] is True
    assert "# top-level comment" in rendered
    assert "# inline comment" in rendered
    assert "# credentials are replaced below" in rendered
