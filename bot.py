#!/usr/bin/env python3
"""BotViajes — modo BOT interactivo de Telegram.

Arranca el motor de vigilancia en segundo plano y escucha comandos de Telegram
para añadir/quitar rutas al vuelo. Además carga las rutas de config.yaml.

  python bot.py

Comandos:
  /vigilar <proveedores>; <origen>; <destino>; <fecha>; [hora]; [precio_max]
  /lista            ver rutas vigiladas
  /borrar <id>      quitar una ruta
  /stop             callar los avisos que estén sonando (sigue vigilando)
  /ayuda
"""

import os
from datetime import datetime

from botviajes.util_env import load_env
load_env()

import telebot

from botviajes.engine import Engine
from botviajes.notifier import Notifier

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN en el .env")

POLL = int(os.environ.get("POLL_INTERVAL", "30"))
ALERT = int(os.environ.get("ALERT_INTERVAL", "10"))

notifier = Notifier(
    tg_token=TOKEN,
    mac_alerts=os.environ.get("MAC_ALERTS", "1") == "1",
    open_browser=os.environ.get("OPEN_BROWSER", "1") == "1",
)
engine = Engine(notifier, poll_interval=POLL, alert_interval=ALERT)

# rutas iniciales de config.yaml (si existe)
try:
    import yaml
    if os.path.exists("config.yaml"):
        with open("config.yaml", "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        engine.seed_from_config(cfg.get("watches"))
except Exception as e:
    print("[bot] aviso al leer config.yaml:", e)

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

AYUDA = (
    "🚆✈️ <b>BotViajes</b>\n\n"
    "Vigila billetes y te avisa en cuanto hay plazas.\n\n"
    "<b>Añadir vigilancia</b> (campos separados por <code>;</code>):\n"
    "<code>/vigilar proveedores; origen; destino; fecha; [hora]; [precio_max]</code>\n\n"
    "Ejemplos:\n"
    "<code>/vigilar renfe; Alicante; Albacete; 24/07/2026; 16:55</code>\n"
    "<code>/vigilar trenes; Madrid; Valencia; 10/08/2026; ; 30</code>\n"
    "<code>/vigilar amadeus; MAD; BCN; 15/08/2026</code>\n\n"
    "• proveedores: <code>renfe</code>, <code>ouigo</code>, <code>iryo</code>, "
    "<code>amadeus</code>, o <code>trenes</code> (todos los de tren)\n"
    "• hora vacía = cualquier tren; precio_max opcional\n\n"
    "<b>Otros:</b>\n"
    "/lista — ver vigilancias\n"
    "/borrar &lt;id&gt; — quitar una\n"
    "/stop — callar avisos que suenan (sigue vigilando)\n"
)


def expand_providers(s):
    s = s.strip().lower()
    if s in ("trenes", "tren"):
        return ["renfe", "ouigo", "iryo"]
    if s in ("all", "todo", "todos"):
        return ["renfe", "ouigo", "iryo", "amadeus"]
    return [p.strip() for p in s.split(",") if p.strip()]


def to_iso(d):
    d = d.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("fecha no válida: %s (usa dd/mm/aaaa)" % d)


@bot.message_handler(commands=["start", "ayuda", "help"])
def _help(m):
    bot.reply_to(m, AYUDA)


@bot.message_handler(commands=["vigilar"])
def _add(m):
    payload = m.text.partition(" ")[2]
    parts = [p.strip() for p in payload.split(";")]
    if len(parts) < 4:
        bot.reply_to(m, "Formato:\n<code>/vigilar proveedores; origen; destino; fecha; "
                        "[hora]; [precio_max]</code>\n\nMira /ayuda para ejemplos.")
        return
    try:
        providers = expand_providers(parts[0])
        origin, destination = parts[1], parts[2]
        date = to_iso(parts[3])
        time_ = parts[4] if len(parts) > 4 else ""
        max_price = float(parts[5].replace(",", ".")) if len(parts) > 5 and parts[5] else None
    except Exception as e:
        bot.reply_to(m, "❌ Error: %s" % e)
        return
    w = engine.add_watch(
        name="%s→%s %s" % (origin, destination, time_ or ""),
        providers=providers, origin=origin, destination=destination,
        date=date, time_=time_, max_price=max_price, chat_id=m.chat.id,
    )
    bot.reply_to(m, "✅ Vigilando <b>#%s</b>: %s→%s el %s %s\nProveedores: %s%s\n\n"
                    "Te aviso aquí en cuanto haya plazas." %
                 (w["id"], origin, destination, parts[3], time_ or "(cualquier hora)",
                  ", ".join(providers),
                  ("\nPrecio máx: %.2f €" % max_price) if max_price else ""))


@bot.message_handler(commands=["lista"])
def _list(m):
    ws = engine.list_watches()
    if not ws:
        bot.reply_to(m, "No hay vigilancias. Añade una con /vigilar (mira /ayuda).")
        return
    lines = ["<b>Vigilancias activas:</b>"]
    for w in ws:
        lines.append("#%s — %s→%s | %s %s | %s%s" % (
            w["id"], w["origin"], w["destination"], w["date"],
            w.get("time") or "(cualquiera)", ", ".join(w["providers"]),
            ("| ≤%.0f€" % w["max_price"]) if w.get("max_price") else ""))
    bot.reply_to(m, "\n".join(lines))


@bot.message_handler(commands=["borrar"])
def _del(m):
    arg = m.text.partition(" ")[2].strip()
    if not arg.isdigit():
        bot.reply_to(m, "Uso: <code>/borrar &lt;id&gt;</code> (mira /lista)")
        return
    ok = engine.remove_watch(int(arg))
    bot.reply_to(m, "🗑️ Borrada #%s" % arg if ok else "No encontré la #%s" % arg)


@bot.message_handler(commands=["stop"])
def _stop(m):
    n = engine.silence_all()
    bot.reply_to(m, "🔕 Avisos callados (%d). Sigo vigilando y te reavisaré si cambia." % n)


def main():
    engine.start_background()
    print("[bot] en marcha. Escríbele /start en Telegram.")
    bot.infinity_polling(skip_pending=True, timeout=30)


if __name__ == "__main__":
    main()
