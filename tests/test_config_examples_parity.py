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
