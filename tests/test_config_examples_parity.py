import tomllib
from pathlib import Path

from backend import config as backend_config

ROOT = Path(__file__).resolve().parent.parent


def test_config_examples_parity():
    fields = set(backend_config.Config.__dataclass_fields__)
    env_keys = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_keys.add(line.split("=", 1)[0].strip())
    with open(ROOT / "config.example.toml", "rb") as f:
        toml_keys = set(tomllib.load(f))
    assert env_keys <= fields
    assert toml_keys <= fields
    # Full parity: every Config field must be documented in both examples
    # (catches missing RATE_* additions like rename/delete/restore/move/templates/tplfolders).
    assert fields <= env_keys, f"missing in .env.example: {sorted(fields - env_keys)}"
    assert fields <= toml_keys, f"missing in config.example.toml: {sorted(fields - toml_keys)}"


def test_rate_scopes_parity():
    from backend.constants import RATE_DEFAULTS

    cfg = backend_config.Config()
    for key in backend_config._RATE_KEYS:
        scope = key.lower()
        attr = f"RATE_{key}_PER_MIN"
        assert attr in backend_config.Config.__dataclass_fields__
        assert attr in backend_config._ENV_KEYS
        assert RATE_DEFAULTS[scope] == (getattr(cfg, attr), 60)
    assert RATE_DEFAULTS["register"] == (cfg.RATE_REGISTER_PER_HOUR, 3600)
