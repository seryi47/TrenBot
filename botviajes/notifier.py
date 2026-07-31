"""Avisos multi-canal: Telegram + Mac (sonido, voz, notificación, abre web).

Los avisos locales de Mac solo se activan en macOS; en Linux (servidor) se
ignoran sin error y el canal efectivo es Telegram.
"""

import os
import re
import subprocess
import sys

import requests

IS_MAC = sys.platform == "darwin"


def chat_ids(value):
    """Normaliza un destino de Telegram a lista de chat ids.

    Admite un id suelto, una lista de YAML, o varios separados por comas o
    espacios ("123,-1001234567890"). Los ids de grupo son negativos.
    """
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else re.split(r"[,\s]+", str(value))
    return [str(i).strip() for i in items if str(i).strip()]


class Notifier:
    def __init__(self, tg_token=None, mac_alerts=True, open_browser=True):
        self.tg_token = tg_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.mac_alerts = mac_alerts
        self.open_browser = open_browser

    # ---- Telegram -----------------------------------------------------------
    def telegram(self, chat_id, text):
        """Envía a uno o varios chats (privados y/o grupos). True si todos OK."""
        ids = chat_ids(chat_id)
        if not self.tg_token or not ids:
            return False
        ok = True
        for cid in ids:
            ok = self._send_one(cid, text) and ok
        return ok

    def _send_one(self, chat_id, text):
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
        if not self.mac_alerts or not IS_MAC:
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
        if not self.open_browser or not url or not IS_MAC:
            return
        try:
            subprocess.run(["open", url], check=False)
        except Exception:
            pass
