#!/usr/bin/env python3
"""BotViajes — modo CONFIG.

Vigila las rutas definidas en config.yaml y avisa por Telegram + Mac.

  python run.py                 # vigilancia continua
  python run.py --once          # una comprobación y muestra el estado
  python run.py --test-telegram # envía un mensaje de prueba
"""

import sys

import yaml

from botviajes.util_env import load_env
load_env()

import os
from botviajes.engine import Engine
from botviajes.notifier import Notifier
from botviajes.providers import get_provider


def load_config(path=None):
    path = path or os.environ.get("BOTVIAJES_CONFIG", "config.yaml")
    if not os.path.exists(path):
        print("No existe %s. Copia config.example.yaml a %s y edítalo." % (path, path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main():
    cfg = load_config()
    chat_id = str(cfg.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    notifier = Notifier(
        mac_alerts=bool(cfg.get("mac_alerts", True)),
        open_browser=bool(cfg.get("open_browser", True)),
    )
    engine = Engine(
        notifier,
        poll_interval=int(cfg.get("poll_interval", 30)),
        alert_interval=int(cfg.get("alert_interval", 10)),
        default_chat_id=chat_id or None,
        max_alerts=int(cfg.get("max_alerts", 120)),
    )
    engine.seed_from_config(cfg.get("watches"))

    if "--test-telegram" in sys.argv:
        ok = notifier.telegram(chat_id, "✅ Prueba de <b>BotViajes</b>. Telegram funciona.")
        print("Telegram:", "ENVIADO" if ok else "FALLO (revisa token/chat_id)")
        return

    if "--check" in sys.argv:
        # Una sola pasada (para cron / GitHub Actions). Avisa y termina.
        n = engine.check_once()
        print("Rutas con plaza en esta pasada: %d" % n)
        return

    print("=" * 64)
    print(" BotViajes — %d rutas vigiladas" % len(engine.watches))
    for w in engine.watches:
        print("  #%s %s [%s] %s %s" % (w["id"], w["name"], ",".join(w["providers"]),
                                       w["date"], w.get("time") or ""))
    print(" Telegram:", "OK" if (notifier.tg_token and chat_id) else "NO configurado")
    print("=" * 64)

    if "--once" in sys.argv:
        for w in engine.watches:
            offers = []
            for pname in w["providers"]:
                try:
                    offers += get_provider(pname).search(w["origin"], w["destination"], w["date"])
                except NotImplementedError:
                    print("  [%s] experimental, sin implementar" % pname)
                except Exception as e:
                    print("  [%s] error: %s" % (pname, e))
            print("\n[%s] %d ofertas:" % (w["name"], len(offers)))
            for o in sorted(offers, key=lambda x: x.departure):
                print("   ", o)
        return

    try:
        engine.run_forever()
    except KeyboardInterrupt:
        print("\nParado por el usuario.")


if __name__ == "__main__":
    main()
