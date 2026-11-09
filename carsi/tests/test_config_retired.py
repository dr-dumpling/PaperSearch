"""Settings no code reads any more leave saved configs and cannot be set (2026-11-09)."""

import json

import pytest

from paper_search_carsi import config as config_mod


def test_retired_settings_leave_a_saved_config_and_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({
        "download_strategy": "fastest", "scihub_domains": ["https://example.org"], "vpnsci_enabled": True,
        "zotero_api_key": "old", "carsi_idp_name": "Fixture University", "publisher_hourly_limit": 40,
    }), encoding="utf-8")
    loaded = config_mod.load_config()
    assert not {"download_strategy", "scihub_domains", "vpnsci_enabled", "zotero_api_key"} & set(loaded)
    assert (loaded["carsi_idp_name"], loaded["publisher_hourly_limit"]) == ("Fixture University", 40)
    config_mod.update_config("publisher_hourly_limit", "50")  # a save keeps only what is used
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "download_strategy" not in saved and saved["publisher_hourly_limit"] == 50
    with pytest.raises(ValueError, match="no longer used"):
        config_mod.update_config("scihub_enabled", "false")


def test_no_default_is_retired():
    assert not config_mod._RETIRED_KEYS & set(config_mod.DEFAULT_CONFIG)
