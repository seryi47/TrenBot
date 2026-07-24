"""Cargador mínimo de .env (sin dependencias externas)."""

import os


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            # no pisar variables ya definidas en el entorno
            os.environ.setdefault(key, val)
