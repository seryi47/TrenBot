#!/usr/bin/env python3
"""BotViajes — modo CONFIG.

Vigila las rutas definidas en config.yaml y avisa por Telegram + Mac.

  python run.py                 # vigilancia continua
  python run.py --once          # una comprobación y muestra el estado
  python run.py --test-telegram # envía un mensaje de prueba
"""

import json
import sys

import yaml

from botviajes.util_env import load_env
load_env()

import os
from botviajes.engine import Engine
from botviajes.notifier import Notifier, chat_ids
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


def latido_diario(engine, notifier, destino, horas=20):
    """Un resumen al día, para que el silencio no se confunda con normalidad.

    Si el job se muriera, dejara de arrancar o alguien desactivara el workflow,
    no llegaría ningún aviso... y eso se parece demasiado a 'no ha cambiado
    nada'. Con un mensaje diario, si un día no llega, es que algo va mal.
    """
    import time as _t
    CLAVE = "_latido"
    ahora = _t.time()
    if ahora - (engine.avisos.get(CLAVE) or {}).get("t", 0) < horas * 3600:
        return
    engine.avisos[CLAVE] = {"t": ahora, "cuando": _t.strftime("%Y-%m-%d %H:%M")}
    engine._guardar_avisos()

    lineas = ["👋 <b>Sigo vigilando</b> — resumen del día", ""]
    try:
        datos = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "web", "datos.json"), encoding="utf-8"))
        dentro = [o for o in datos["opciones"] if o.get("dentro_presupuesto")]
        tope = datos["viaje"]["tope_por_persona"]
        if dentro:
            mejor = min(dentro, key=lambda o: o["total_persona"])
            lineas.append("Mejor combinación ahora: <b>%s</b> por <b>%.2f €</b> "
                          "por persona." % (mejor["titulo"], mejor["total_persona"]))
            if len(dentro) > 1:
                lineas.append("Hay %d por debajo de %d €." % (len(dentro), tope))
        else:
            barata = min(datos["opciones"], key=lambda o: o["total_persona"] or 9e9)
            lineas.append("Ninguna combinación baja de %d € por persona. La más "
                          "barata es <b>%s</b>, %.2f €."
                          % (tope, barata["titulo"], barata["total_persona"]))
    except Exception:
        lineas.append("(no he podido leer el resumen de precios)")
    activas = [w for w in engine.watches if w.get("enabled", True)]
    ciegas = [k for k in engine.avisos if k != CLAVE]
    lineas += ["", "Vigilando %d vuelos.%s" % (len(activas),
               " ⚠️ %d sin datos ahora mismo." % len(ciegas) if ciegas else ""),
               "🌐 https://viaje-octubre.vercel.app"]
    notifier.telegram(destino, "\n".join(lineas))
    print("  [latido] resumen diario enviado")


def publicar_web():
    """Regenera web/datos.json con los precios de ahora y lo sube al repo.

    Vercel está conectado a este repositorio, así que el propio commit
    republica el panel: no hace falta ni token de Vercel ni el ordenador.
    """
    import subprocess
    raiz = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run([sys.executable, os.path.join(raiz, "actualizar_web.py")],
                       cwd=raiz, capture_output=True, text=True)
    if r.returncode != 0:
        print("  [web] no se pudo regenerar:", (r.stderr or "")[-200:].strip())
        return
    commit_al_repo(["historico.json", "avisos.json",
                    os.path.join("web", "datos.json"),
                    os.path.join("data", "ryanair_version.json"),
                    os.path.join("data", "wizz_version.json"),
                    os.path.join("data", "wizz_horarios.json")],
                   "chore: precios actualizados")
    print("  [web] datos publicados")


def save_and_commit_watches(engine, path=None):
    """Vuelca la watchlist a watches.yaml y (en la nube) la commitea al repo,
    para que los cambios por comando sobrevivan al relevo del job."""
    path = path or os.environ.get("BOTVIAJES_CONFIG", "watches.yaml")
    base = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            base = yaml.safe_load(fh) or {}
    base["watches"] = [_watch_to_yaml(w) for w in engine.list_watches()]
    base["paused"] = bool(engine.paused)   # que /pausa sobreviva al relevo del job
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(base, fh, allow_unicode=True, sort_keys=False)

    commit_al_repo([path], "chore: watches actualizadas desde Telegram")


def commit_al_repo(rutas, mensaje):
    """Sube al repo los ficheros indicados (solo en la nube, GIT_COMMIT_BACK=1).

    Es lo que permite que el bot NO dependa de tener el Mac encendido: el job de
    GitHub Actions guarda aquí los precios nuevos y la web, y como Vercel está
    conectado al repo, cada commit republica el panel solo.
    """
    if os.environ.get("GIT_COMMIT_BACK", "1") != "1":
        return
    import subprocess

    def run(*a):
        return subprocess.run(a, capture_output=True, text=True)

    branch = os.environ.get("GIT_BRANCH", "main")
    run("git", "config", "user.email", "bot@users.noreply.github.com")
    run("git", "config", "user.name", "BotViajes")
    existentes = [r for r in rutas if os.path.exists(r)]
    if not existentes:
        return
    run("git", "add", *existentes)
    if run("git", "commit", "-m", mensaje).returncode != 0:
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


def disable_workflow():
    """Desactiva el workflow desde dentro del propio job (/apagar), para que el
    cron no lo relance a los 5 minutos. Necesita `permissions: actions: write`.

    Devuelve (ok, detalle). Fuera de Actions no hace nada.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    wf = os.environ.get("WORKFLOW_FILE", "vigilar.yml")
    if not token or not repo:
        return False, "no estoy en GitHub Actions"
    import requests
    try:
        r = requests.put(
            "https://api.github.com/repos/%s/actions/workflows/%s/disable" % (repo, wf),
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=20,
        )
        return r.ok, "HTTP %s %s" % (r.status_code, (r.text or "")[:150])
    except Exception as e:
        return False, str(e)


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
    engine.set_paused(bool(cfg.get("paused", False)))   # /pausa persistida

    if "--chat-ids" in sys.argv:
        # Descubre el id de los chats/grupos donde está el bot: mete el bot en el
        # grupo, escribe algo ahí y lanza esto. Los grupos tienen id NEGATIVO.
        from botviajes import commands
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            print("Falta TELEGRAM_BOT_TOKEN en el .env")
            return
        try:
            updates, _ = commands.get_updates(token, None, timeout=5)
        except Exception as e:
            if "409" in str(e):
                print("Telegram devuelve 409 (Conflict): ya hay otro proceso leyendo\n"
                      "los mensajes de este bot (el bucle de GitHub Actions con\n"
                      "HANDLE_COMMANDS=1, o un bot.py local). Páralo un momento\n"
                      "(Actions → run en curso → Cancel, o `pkill -f bot.py`) y reintenta.\n"
                      "Alternativa: añade @RawDataBot al grupo y mira el campo chat.id.")
            else:
                print("Error consultando Telegram:", e)
            return
        seen = {}
        for u in updates:
            msg = u.get("message") or u.get("edited_message") or {}
            ch = msg.get("chat") or {}
            if ch.get("id") is not None:
                seen[str(ch["id"])] = "%s — %s" % (
                    ch.get("type", "?"), ch.get("title") or ch.get("first_name") or "")
        if not seen:
            print("Sin mensajes recientes. Escribe algo en el chat/grupo y reintenta.\n"
                  "(Telegram solo guarda los updates ~24 h.)")
        for cid, desc in seen.items():
            print("  %-16s %s" % (cid, desc))
        return

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
        # chats autorizados a mandar comandos: el privado y/o los grupos
        # configurados en TELEGRAM_CHAT_ID (separados por comas)
        owner_chats = os.environ.get("TELEGRAM_CHAT_ID", "")
        allowed = set(chat_ids(owner_chats))
        start = _t.time()
        last_check = 0.0
        offset = None
        print("Modo BUCLE: sondeo cada %ds, comandos=%s, máx %ds." %
              (interval, handle_cmds, max_runtime))
        while _t.time() - start < max_runtime:
            if _t.time() - last_check >= interval:
                try:
                    engine.historial_cambiado = False
                    engine.check_once()
                    if engine.historial_cambiado:
                        publicar_web()
                    latido_diario(engine, notifier, owner_chats)
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
                        if allowed and chat not in allowed:
                            continue  # solo los chats autorizados mandan comandos
                        reply, ch = commands.handle_text(msg.get("text", ""), chat, engine)
                        if reply:
                            notifier.telegram(chat, reply)
                        changed = changed or ch
                    if changed:
                        save_and_commit_watches(engine)
                    if engine.shutdown_requested:
                        ok, detalle = disable_workflow()
                        print("  /apagar -> desactivar workflow:", ok, detalle)
                        notifier.telegram(
                            owner_chats,
                            "🔌 Apagado. El workflow queda <b>desactivado</b>, no me relanzará el cron."
                            if ok else
                            "⚠️ Me paro, pero <b>no pude desactivar el workflow</b> (%s).\n"
                            "El cron me relanzará en ~5 min. Desactívalo con:\n"
                            "<code>gh workflow disable vigilar.yml</code>" % detalle)
                        break
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
            if not w.get("enabled", True):
                print("\n[%s] desactivada, no se consulta" % w["name"])
                continue
            coinciden, todas, bajada = engine.revisar(w)
            objetivo = ("  objetivo ≤%.0f €" % w["max_price"]) if w.get("max_price") else ""
            print("\n[%s] %d ofertas, %d dentro del objetivo%s"
                  % (w["name"], len(todas), len(coinciden), objetivo))
            for o in sorted(todas, key=lambda x: x.departure):
                print("   ", o)
            if bajada:
                print("    📉 HA BAJADO respecto a la última consulta")
        return

    try:
        engine.run_forever()
    except KeyboardInterrupt:
        print("\nParado por el usuario.")


if __name__ == "__main__":
    main()
