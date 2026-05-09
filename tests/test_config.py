"""Tests for ``splice_kicad_plugin.config``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from splice_kicad_plugin.config import (
    DEFAULT_BASE_URL,
    Config,
    config_path,
)
from splice_kicad_plugin.errors import ConfigLoadError


@pytest.fixture
def tmp_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config to a tmp file via the SPLICE_KICAD_CONFIG override."""
    p = tmp_path / "kicad-plugin.json"
    monkeypatch.setenv("SPLICE_KICAD_CONFIG", str(p))
    return p


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "custom.json"
    monkeypatch.setenv("SPLICE_KICAD_CONFIG", str(p))
    assert config_path() == p


def test_default_path_per_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPLICE_KICAD_CONFIG", raising=False)
    p = config_path()
    # Whatever platform we're on, the path resolves to a real Path under home
    # or APPDATA, ending in our filename.
    assert p.name == "kicad-plugin.json"
    assert "Splice" in p.parts or "splice" in p.parts


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_defaults(tmp_config_path: Path) -> None:
    assert not tmp_config_path.exists()
    cfg = Config.load()
    assert cfg.api_key is None
    assert cfg.base_url == DEFAULT_BASE_URL
    assert not cfg.is_configured


def test_load_full_config(tmp_config_path: Path) -> None:
    tmp_config_path.write_text(
        json.dumps(
            {"api_key": "splice_abcd", "base_url": "http://localhost:5002"}
        ),
        encoding="utf-8",
    )
    cfg = Config.load()
    assert cfg.api_key == "splice_abcd"
    assert cfg.base_url == "http://localhost:5002"
    assert cfg.is_configured


def test_load_only_api_key_uses_default_url(tmp_config_path: Path) -> None:
    tmp_config_path.write_text(json.dumps({"api_key": "splice_x"}), encoding="utf-8")
    cfg = Config.load()
    assert cfg.api_key == "splice_x"
    assert cfg.base_url == DEFAULT_BASE_URL


def test_load_empty_api_key_remains_unconfigured(tmp_config_path: Path) -> None:
    tmp_config_path.write_text(json.dumps({"api_key": ""}), encoding="utf-8")
    cfg = Config.load()
    assert cfg.api_key is None
    assert not cfg.is_configured


def test_load_invalid_json_raises(tmp_config_path: Path) -> None:
    tmp_config_path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        Config.load()


def test_load_non_object_raises(tmp_config_path: Path) -> None:
    tmp_config_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        Config.load()


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def test_save_round_trip(tmp_config_path: Path) -> None:
    cfg = Config(api_key="splice_xyz", base_url="http://localhost:5002")
    cfg.save()
    loaded = Config.load()
    assert loaded.api_key == "splice_xyz"
    assert loaded.base_url == "http://localhost:5002"


def test_fuzzy_property_matching_default_true(tmp_config_path: Path) -> None:
    # Missing → True (default)
    cfg = Config.load()
    assert cfg.fuzzy_property_matching is True


def test_fuzzy_property_matching_persisted_false(tmp_config_path: Path) -> None:
    Config(api_key="x", fuzzy_property_matching=False).save()
    loaded = Config.load()
    assert loaded.fuzzy_property_matching is False


def test_fuzzy_property_matching_persisted_true(tmp_config_path: Path) -> None:
    Config(api_key="x", fuzzy_property_matching=True).save()
    loaded = Config.load()
    assert loaded.fuzzy_property_matching is True


def test_fuzzy_property_matching_legacy_config_defaults_true(
    tmp_config_path: Path,
) -> None:
    # Older config files won't have the field; default to True.
    import json
    tmp_config_path.write_text(
        json.dumps({"api_key": "splice_old"}), encoding="utf-8"
    )
    loaded = Config.load()
    assert loaded.fuzzy_property_matching is True


def test_prefer_desktop_when_running_default_true(tmp_config_path: Path) -> None:
    cfg = Config.load()
    assert cfg.prefer_desktop_when_running is True


def test_prefer_desktop_when_running_round_trip(tmp_config_path: Path) -> None:
    Config(api_key="x", prefer_desktop_when_running=False).save()
    loaded = Config.load()
    assert loaded.prefer_desktop_when_running is False


def test_prefer_desktop_when_running_legacy_config(tmp_config_path: Path) -> None:
    import json
    tmp_config_path.write_text(
        json.dumps({"api_key": "splice_old"}), encoding="utf-8"
    )
    loaded = Config.load()
    assert loaded.prefer_desktop_when_running is True


# ---------------------------------------------------------------------------
# connector_prefixes
# ---------------------------------------------------------------------------


def test_connector_prefixes_default_none(tmp_config_path: Path) -> None:
    cfg = Config.load()
    assert cfg.connector_prefixes is None


def test_connector_prefixes_round_trip(tmp_config_path: Path) -> None:
    Config(api_key="x", connector_prefixes=["J", "CN", "X"]).save()
    loaded = Config.load()
    assert loaded.connector_prefixes == ["J", "CN", "X"]


def test_connector_prefixes_empty_list_serializes_as_none(
    tmp_config_path: Path,
) -> None:
    # Defensive: empty list shouldn't round-trip as empty — should normalize
    # to None so the extractor falls back to the canonical defaults.
    import json
    tmp_config_path.write_text(
        json.dumps({"api_key": "x", "connector_prefixes": []}),
        encoding="utf-8",
    )
    loaded = Config.load()
    assert loaded.connector_prefixes is None


def test_connector_prefixes_normalizes_case(tmp_config_path: Path) -> None:
    import json
    tmp_config_path.write_text(
        json.dumps({"api_key": "x", "connector_prefixes": [" j ", "Cn"]}),
        encoding="utf-8",
    )
    loaded = Config.load()
    # Tokens get uppercased + stripped on load.
    assert loaded.connector_prefixes == ["J", "CN"]


def test_connector_prefixes_save_omits_field_when_none(
    tmp_config_path: Path,
) -> None:
    Config(api_key="x", connector_prefixes=None).save()
    import json
    payload = json.loads(tmp_config_path.read_text(encoding="utf-8"))
    # Field is omitted when None so legacy loaders don't see surprising data.
    assert "connector_prefixes" not in payload


def test_save_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nested = tmp_path / "a" / "b" / "kicad-plugin.json"
    monkeypatch.setenv("SPLICE_KICAD_CONFIG", str(nested))
    Config(api_key="x").save()
    assert nested.exists()


def test_save_sets_user_only_perms_on_unix(tmp_config_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("perm check is unix-only")
    Config(api_key="secret").save()
    mode = tmp_config_path.stat().st_mode & 0o777
    assert mode == 0o600
