"""Avisos multi-canal: Telegram + Mac (sonido, voz, notificación, abre web)."""

import os
import subprocess

import requests


class Notifier:
    def __init__(self, tg_token=None, mac_alerts=True, open_browser=True):
        self.tg_token = tg_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.mac_alerts = mac_alerts
        self.open_browser = open_browser

    # ---- Telegram -----------------------------------------------------------
    def telegram(self, chat_id, text):
        if not self.tg_token or not chat_id:
            return False
        try:
            r = requests.post(
                "https://api.telegram.org/bot%s/sendMessage" % self.tg_token,
                data={
                    "chat_id": str(chat_id),
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "false",
                },
                timeout=20,
            )
            if not r.ok:
                print("  [telegram] %s: %s" % (r.status_code, r.text[:200]))
            return r.ok
        except Exception as e:
            print("  [telegram] error:", e)
            return False

    # ---- Mac ----------------------------------------------------------------
    def mac(self, title, message):
        if not self.mac_alerts:
            return
        try:
            subprocess.run(
                ["osascript", "-e",
                 'display notification %r with title %r sound name "Glass"'
                 % (message, title)],
                check=False,
            )
            for _ in range(3):
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
            subprocess.run(
                ["say", "¡Hay billetes disponibles! ¡Corre a comprar!"], check=False
            )
        except Exception as e:
            print("  [mac] error:", e)

    def browser(self, url):
        if not self.open_browser or not url:
            return
        try:
            subprocess.run(["open", url], check=False)
        except Exception:
            pass
