"""API key file and CLI. No database."""

import json
import stat

import pytest

from graph_memory_mcp.cli import main
from graph_memory_mcp.graph_memory import api_keys
from graph_memory_mcp.graph_memory.api_keys import (
    TokenModeConfigError,
    create_key,
    key_for_bearer,
    set_projects,
    validate_token_mode,
)


def test_create_stores_the_hash_and_not_the_key(tmp_path):
    path = tmp_path / "keys.json"
    record, raw = create_key(path, "alice", ["p1", "p2"])
    text = path.read_text(encoding="utf-8")
    stored = json.loads(text)
    row = stored["keys"][0]
    assert row["id"] == record.id
    assert row["name"] == "alice"
    assert row["projects"] == ["p1", "p2"]
    assert "owner" not in row
    assert row["revoked"] is False
    assert raw not in text
    assert row["hash"] != raw
    found = key_for_bearer(path, f"Bearer {raw}")
    assert found is not None
    assert found.name == "alice"
    assert found.projects == ("p1", "p2")
    assert key_for_bearer(path, None) is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_create_rejects_a_bad_name_or_project(tmp_path):
    with pytest.raises(ValueError, match="owner_id"):
        create_key(tmp_path / "keys.json", "alice/bob", ["p1"])
    with pytest.raises(ValueError, match="owner_id"):
        create_key(tmp_path / "keys.json", "alice", ["p1/p2"])


def test_reads_legacy_owner_format(tmp_path):
    path = tmp_path / "keys.json"
    raw = "gmk_legacy"
    path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "id": "k_old",
                        "owner": "alice",
                        "hash": api_keys.hash_key(raw),
                        "created_at": "2026-10-22T18:00:00+00:00",
                        "revoked": False,
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    found = key_for_bearer(path, f"Bearer {raw}")
    assert found is not None
    assert found.name == "alice"
    assert found.projects == ("alice",)


def test_keys_cli_create_list_set_projects_revoke(tmp_path, capsys):
    path = tmp_path / "keys.json"
    main(
        [
            "keys",
            "create",
            "--name",
            "alice",
            "--projects",
            "p1,p2",
            "--file",
            str(path),
        ]
    )
    created = capsys.readouterr().out.strip().splitlines()
    assert created[0].startswith("id: k_")
    assert created[1] == "name: alice"
    assert created[2] == "projects: p1,p2"
    raw = created[3]
    key_id = created[0].split(": ", 1)[1]
    assert raw not in path.read_text(encoding="utf-8")

    main(["keys", "list", "--file", str(path)])
    listed = capsys.readouterr().out
    assert key_id in listed
    assert "alice" in listed
    assert "p1,p2" in listed
    assert "active" in listed
    assert raw not in listed

    main(["keys", "set-projects", key_id, "p1,p3", "--file", str(path)])
    updated = capsys.readouterr().out
    assert "p1,p3" in updated
    assert key_for_bearer(path, f"Bearer {raw}").projects == ("p1", "p3")

    main(["keys", "revoke", key_id, "--file", str(path)])
    assert "revoked" in capsys.readouterr().out
    assert key_for_bearer(path, f"Bearer {raw}") is None

    main(["keys", "list", "--file", str(path)])
    assert "revoked" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        main(["keys", "revoke", "k_missing", "--file", str(path)])
    assert exc.value.code == 1


def test_set_projects_unknown_id(tmp_path):
    path = tmp_path / "keys.json"
    create_key(path, "alice", ["p1"])
    assert set_projects(path, "k_missing", ["p2"]) is None


def test_owner_lookup_rereads_the_file_when_it_changes(tmp_path, monkeypatch):
    path = tmp_path / "keys.json"
    _record, raw = create_key(path, "alice", ["p1"])
    calls = {"n": 0}
    original = api_keys._read

    def counting(file_path):
        calls["n"] += 1
        return original(file_path)

    monkeypatch.setattr(api_keys, "_read", counting)
    assert key_for_bearer(path, f"Bearer {raw}").name == "alice"
    assert key_for_bearer(path, f"Bearer {raw}").name == "alice"
    assert calls["n"] == 1

    text = path.read_text(encoding="utf-8").replace(
        '"revoked": false', '"revoked": true'
    )
    path.write_text(text, encoding="utf-8")
    assert key_for_bearer(path, f"Bearer {raw}") is None
    assert calls["n"] == 2


def test_token_mode_refuses_to_start_without_admin_token_or_keys(tmp_path):
    path = tmp_path / "keys.json"
    create_key(path, "alice", ["p1"])
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


def test_keys_cli_rejects_a_bad_name(tmp_path):
    with pytest.raises(SystemExit):
        main(
            [
                "keys",
                "create",
                "--name",
                "no spaces",
                "--projects",
                "p1",
                "--file",
                str(tmp_path / "k.json"),
            ]
        )
