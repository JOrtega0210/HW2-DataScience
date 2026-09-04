"""Carga los parametros del pipeline desde el bloque yaml de config.md."""

import re
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_MD = ROOT / "config.md"

_YAML_FENCE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


@lru_cache(maxsize=1)
def load_config(config_path: Path = CONFIG_MD) -> dict:
    text = Path(config_path).read_text(encoding="utf-8")
    match = _YAML_FENCE.search(text)
    if not match:
        raise ValueError(f"No se encontro un bloque ```yaml``` en {config_path}")
    return yaml.safe_load(match.group(1))


def path_for(key: str) -> Path:
    cfg = load_config()
    return ROOT / cfg["paths"][key]


if __name__ == "__main__":
    import json

    print(json.dumps(load_config(), indent=2, ensure_ascii=False))
