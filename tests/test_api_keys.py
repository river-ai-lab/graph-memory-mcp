"""API key file and CLI. No database."""

import json

import pytest

from graph_memory_mcp.cli import main
from graph_memory_mcp.graph_memory import api_keys
from graph_memory_mcp.graph_memory.api_keys import (
    TokenModeConfigError,
    create_key,
    owner_for_bearer,
    validate_token_mode,
)


def test_create_stores_the_hash_and_not_the_key(tmp_path):
    path = tmp_path / "keys.json"
    record, raw = create_key(path, "alice")
    text = path.read_text(encoding="utf-8")
    stored = json.loads(text)
    row = stored["keys"][0]
    assert row["id"] == record.id
    assert row["owner"] == "alice"
    assert row["revoked"] is False
    assert raw not in text
    assert row["hash"] != raw
    assert owner_for_bearer(path, f"Bearer {raw}") == "alice"
    assert owner_for_bearer(path, None) is None


def test_create_rejects_a_bad_owner(tmp_path):
    with pytest.raises(ValueError, match="owner_id"):
        create_key(tmp_path / "keys.json", "alice/bob")


def test_keys_cli_create_list_revoke(tmp_path, capsys):
    path = tmp_path / "keys.json"
    main(["keys", "create", "--owner", "alice", "--file", str(path)])
    created = capsys.readouterr().out.strip().splitlines()
    assert created[0].startswith("id: k_")
    assert created[1] == "owner: alice"
    raw = created[2]
    key_id = created[0].split(": ", 1)[1]
    assert raw not in path.read_text(encoding="utf-8")

    main(["keys", "list", "--file", str(path)])
    listed = capsys.readouterr().out
    assert key_id in listed
    assert "alice" in listed
    assert "active" in listed
    assert raw not in listed

    main(["keys", "revoke", key_id, "--file", str(path)])
    assert "revoked" in capsys.readouterr().out
    assert owner_for_bearer(path, f"Bearer {raw}") is None

    main(["keys", "list", "--file", str(path)])
    assert "revoked" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        main(["keys", "revoke", "k_missing", "--file", str(path)])
    assert exc.value.code == 1


def test_owner_lookup_rereads_the_file_when_it_changes(tmp_path, monkeypatch):
    path = tmp_path / "keys.json"
    _record, raw = create_key(path, "alice")
    calls = {"n": 0}
    original = api_keys._read

    def counting(file_path):
        calls["n"] += 1
        return original(file_path)

    monkeypatch.setattr(api_keys, "_read", counting)
    assert owner_for_bearer(path, f"Bearer {raw}") == "alice"
    assert owner_for_bearer(path, f"Bearer {raw}") == "alice"
    assert calls["n"] == 1

    text = path.read_text(encoding="utf-8").replace(
        '"revoked": false', '"revoked": true'
    )
    path.write_text(text, encoding="utf-8")
    assert owner_for_bearer(path, f"Bearer {raw}") is None
    assert calls["n"] == 2


def test_token_mode_refuses_to_start_without_admin_token_or_keys(tmp_path):
    path = tmp_path / "keys.json"
    create_key(path, "alice")
    with pytest.raises(TokenModeConfigError, match="ADMIN_TOKEN"):
        validate_token_mode(admin_token="", keys_file=str(path))
    missing = tmp_path / "missing.json"
    with pytest.raises(TokenModeConfigError, match="requires an API keys file"):
        validate_token_mode(admin_token="secret", keys_file=str(missing))
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(TokenModeConfigError, match="cannot be read"):
        validate_token_mode(admin_token="secret", keys_file=str(broken))
    validate_token_mode(admin_token="secret", keys_file=str(path))


def test_keys_cli_rejects_a_bad_owner(tmp_path):
    with pytest.raises(SystemExit):
        main(
            [
                "keys",
                "create",
                "--owner",
                "no spaces",
                "--file",
                str(tmp_path / "k.json"),
            ]
        )
