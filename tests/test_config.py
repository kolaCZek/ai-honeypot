from pathlib import Path

import pytest

from shared.config import load_config


def test_load_example(tmp_path: Path):
    src = Path(__file__).resolve().parents[1] / "config.yaml.example"
    cfg_txt = src.read_text().replace("/data/secret.key", str(tmp_path / "secret.key"))
    cfg_txt = cfg_txt.replace("/data/honeypot.db", str(tmp_path / "h.db"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(cfg_txt)

    s = load_config(cfg)
    assert s.llm.model
    assert s.honeypot.port == 8888
    assert s.dashboard.basic_auth.username == "admin"
    assert len(s.secret_key) == 32
    # File created.
    assert Path(s.honeypot.secret_key_file).exists()


def test_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_secret_key_persists(tmp_path: Path):
    src = Path(__file__).resolve().parents[1] / "config.yaml.example"
    cfg_txt = src.read_text().replace("/data/secret.key", str(tmp_path / "secret.key"))
    cfg_txt = cfg_txt.replace("/data/honeypot.db", str(tmp_path / "h.db"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(cfg_txt)

    s1 = load_config(cfg)
    s2 = load_config(cfg)
    assert s1.secret_key == s2.secret_key
