#!/usr/bin/env python3
"""BotViajes — modo BOT interactivo de Telegram (para una máquina propia).

Arranca el motor de vigilancia en segundo plano y escucha comandos de Telegram
por long-polling. Usa la misma lógica de comandos que el bucle de la nube
(botviajes/commands.py).

  python bot.py

Comandos: /vigilar, /lista, /borrar, /stop, /ayuda  (ver /ayuda).
"""

import os

from botviajes.util_env import load_env
load_env()

import telebot

from botviajes import commands
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
engine = Engine(notifier, poll_interval=POLL, alert_interval=ALERT,
                default_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None)

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


@bot.message_handler(func=lambda m: True)
def _any(m):
    reply, _changed = commands.handle_text(m.text, m.chat.id, engine)
    if reply:
        bot.reply_to(m, reply)


def main():
    engine.start_background()
    print("[bot] en marcha. Escríbele /start en Telegram.")
    bot.infinity_polling(skip_pending=True, timeout=30)


if __name__ == "__main__":
    main()
