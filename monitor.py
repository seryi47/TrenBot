#!/usr/bin/env python3
"""Vigilante del viaje: sondea, avisa por Telegram y republica la web.

    ./venv/bin/python monitor.py                 # bucle cada 15 min
    ./venv/bin/python monitor.py --cada 1800     # cada 30 min
    ./venv/bin/python monitor.py --una-vez       # una pasada y sale

En cada vuelta:
  1. consulta el precio real de cada tramo vigilado (Ryanair y Wizz),
  2. avisa por Telegram si baja 3 € o más, o si cruza el objetivo,
  3. regenera web/datos.json con esos mismos precios,
  4. publica en Vercel SOLO si algún precio ha cambiado (para no quemar
     despliegues: el plan gratuito tiene un tope diario).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botviajes.engine import Engine          # noqa: E402
from botviajes.notifier import Notifier      # noqa: E402
from botviajes.util_env import load_env      # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(RAIZ, "web")
HUELLA = os.path.join(RAIZ, ".ultimo_desplegado")


def huella_precios():
    """Resumen de los precios publicados, para saber si hace falta redesplegar."""
    d = json.load(open(os.path.join(WEB, "datos.json"), encoding="utf-8"))
    firma = [(t.get("de"), t.get("a"), t.get("fecha"), t.get("precio"), t.get("estado"))
             for o in d["opciones"] for t in o["tramos"] if t["tipo"] == "vuelo"]
    return hashlib.sha1(json.dumps(sorted(map(str, firma))).encode()).hexdigest()


def desplegar():
    r = subprocess.run(["vercel", "deploy", "--prod", "--yes"], cwd=WEB,
                       capture_output=True, text=True)
    ok = r.returncode == 0
    print("   %s" % ("publicado en Vercel" if ok else
                     "fallo al publicar: " + (r.stderr or "")[-200:].strip()))
    return ok


def una_vuelta(engine, desplegar_web=True):
    sello = datetime.now().strftime("%H:%M:%S")
    activas = sum(1 for w in engine.watches if w.get("enabled", True))
    print("\n[%s] revisando %d rutas..." % (sello, activas))
    engine.check_once()                       # consulta + avisos de Telegram

    subprocess.run([sys.executable, os.path.join(RAIZ, "actualizar_web.py")],
                   cwd=RAIZ, capture_output=True, text=True)
    nueva = huella_precios()
    anterior = open(HUELLA).read().strip() if os.path.exists(HUELLA) else ""
    if nueva == anterior:
        print("   sin cambios de precio; no hace falta republicar")
        return
    if desplegar_web and desplegar():
        open(HUELLA, "w").write(nueva)
    elif not desplegar_web:
        open(HUELLA, "w").write(nueva)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cada", type=int, default=900, help="segundos entre vueltas")
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--sin-web", action="store_true", help="no publicar en Vercel")
    args = ap.parse_args()

    load_env()
    notifier = Notifier(mac_alerts=os.environ.get("MAC_ALERTS", "1") != "0",
                        open_browser=False)
    engine = Engine(notifier,
                    default_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
                    state_file=os.path.join(RAIZ, "watches.json"))
    activas = [w for w in engine.watches if w.get("enabled", True)]
    print("Vigilando %d rutas cada %d min. Ctrl-C para parar." %
          (len(activas), args.cada // 60))

    if args.una_vez:
        una_vuelta(engine, not args.sin_web)
        return
    try:
        while True:
            una_vuelta(engine, not args.sin_web)
            time.sleep(args.cada)
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    main()
