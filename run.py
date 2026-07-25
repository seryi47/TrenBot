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


def _watch_to_yaml(w):
    d = {"name": w["name"], "providers": w["providers"],
         "origin": w["origin"], "destination": w["destination"], "date": w["date"]}
    if w.get("time"):
        d["time"] = w["time"]
    if w.get("max_price") is not None:
        d["max_price"] = w["max_price"]
    return d


def save_and_commit_watches(engine, path=None):
    """Vuelca la watchlist a watches.yaml y (en la nube) la commitea al repo,
    para que los cambios por comando sobrevivan al relevo del job."""
    path = path or os.environ.get("BOTVIAJES_CONFIG", "watches.yaml")
    base = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            base = yaml.safe_load(fh) or {}
    base["watches"] = [_watch_to_yaml(w) for w in engine.list_watches()]
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(base, fh, allow_unicode=True, sort_keys=False)

    if os.environ.get("GIT_COMMIT_BACK", "1") != "1":
        return
    import subprocess

    def run(*a):
        return subprocess.run(a, capture_output=True, text=True)

    branch = os.environ.get("GIT_BRANCH", "main")
    run("git", "config", "user.email", "bot@users.noreply.github.com")
    run("git", "config", "user.name", "BotViajes")
    run("git", "add", path)
    if run("git", "commit", "-m", "chore: watches actualizadas desde Telegram").returncode != 0:
        return  # nada que commitear
    # el runner está en detached HEAD; rebase sobre lo último y push explícito a la rama
    run("git", "fetch", "origin", branch)
    if run("git", "rebase", "origin/" + branch).returncode != 0:
        run("git", "rebase", "--abort")
        print("  [git] conflicto al rebasar; no hago push (se reintenta al siguiente cambio)")
        return
    p = run("git", "push", "origin", "HEAD:" + branch)
    if p.returncode != 0:
        print("  [git] push falló:", (p.stderr or "").strip()[:200])


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

    if "--loop" in sys.argv:
        # Bucle para GitHub Actions: sondea cada LOOP_INTERVAL s durante como mucho
        # MAX_RUNTIME_SECONDS (releva antes del corte de 6 h de GitHub). Si
        # HANDLE_COMMANDS=1, además atiende comandos de Telegram por getUpdates.
        import time as _t
        from botviajes import commands
        interval = int(os.environ.get("LOOP_INTERVAL", "60"))
        max_runtime = int(os.environ.get("MAX_RUNTIME_SECONDS", "20000"))  # ~5h33m
        handle_cmds = os.environ.get("HANDLE_COMMANDS", "0") == "1"
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        owner = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
        start = _t.time()
        last_check = 0.0
        offset = None
        print("Modo BUCLE: sondeo cada %ds, comandos=%s, máx %ds." %
              (interval, handle_cmds, max_runtime))
        while _t.time() - start < max_runtime:
            if _t.time() - last_check >= interval:
                try:
                    engine.check_once()
                except Exception as e:
                    print("  error en pasada:", e)
                last_check = _t.time()

            if handle_cmds and token:
                try:
                    updates, offset = commands.get_updates(token, offset, timeout=20)
                    changed = False
                    for u in updates:
                        msg = u.get("message") or u.get("edited_message") or {}
                        chat = str((msg.get("chat") or {}).get("id", ""))
                        if owner and chat != owner:
                            continue  # solo el dueño puede mandar comandos
                        reply, ch = commands.handle_text(msg.get("text", ""), chat, engine)
                        if reply:
                            notifier.telegram(chat, reply)
                        changed = changed or ch
                    if changed:
                        save_and_commit_watches(engine)
                except Exception as e:
                    print("  error atendiendo comandos:", e)
            else:
                _t.sleep(max(1, interval - (_t.time() - last_check)))

            if _t.time() - start + 1 >= max_runtime:
                break
        print("Fin del bucle (relevo al siguiente run).")
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
