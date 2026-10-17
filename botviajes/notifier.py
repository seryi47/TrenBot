"""Avisos multi-canal: Telegram + LINE + Mac (sonido, voz, notificación, abre web).

Los avisos locales de Mac solo se activan en macOS; en Linux (servidor) se
ignoran sin error y los canales efectivos son Telegram y, si está
configurado, LINE.
"""

import os
import re
import subprocess
import sys

import requests

IS_MAC = sys.platform == "darwin"


def chat_ids(value):
    """Normaliza un destino (Telegram o LINE) a lista de ids.

    Admite un id suelto, una lista de YAML, o varios separados por comas o
    espacios ("123,-1001234567890"). Los ids de grupo de Telegram son
    negativos; los de LINE (userId/groupId) son cadenas alfanuméricas.
    """
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else re.split(r"[,\s]+", str(value))
    return [str(i).strip() for i in items if str(i).strip()]


_TAGS_HTML = re.compile(r"</?(?:b|i|s|u|code|pre)>")
_LINK_HTML = re.compile(r'<a href="([^"]*)">([^<]*)</a>')
_ENTIDADES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}


def _a_texto_plano(html):
    """Los avisos se escriben pensando en el HTML de Telegram (<b>, <a href>);
    LINE no entiende HTML, manda texto plano. En vez de mantener dos plantillas
    de cada mensaje, se escribe una vez y se convierte aquí."""
    t = _LINK_HTML.sub(lambda m: "%s (%s)" % (m.group(2), m.group(1)), html)
    t = _TAGS_HTML.sub("", t)
    for ent, ch in _ENTIDADES.items():
        t = t.replace(ent, ch)
    return t


class Notifier:
    def __init__(self, tg_token=None, line_token=None, line_to=None,
                mac_alerts=True, open_browser=True):
        self.tg_token = tg_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.line_token = line_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
        self.line_to = line_to or os.environ.get("LINE_USER_ID", "").strip()
        self.mac_alerts = mac_alerts
        self.open_browser = open_browser
        # Destinos que ya no existen (grupo borrado, bot expulsado, bloqueado).
        # Se avisa una vez y se dejan de reintentar: si no, cada alerta escupe
        # un 403 y parece que el bot falla cuando en realidad sí está avisando.
        self._muertos = set()

    # ---- multi-canal ----------------------------------------------------------
    def avisar(self, chat_id, text):
        """Manda el mismo aviso a Telegram y, si hay LINE configurado, a LINE.

        Devuelve lo que devuelve Telegram (el canal "principal": es el que ya
        usaba todo el código para decidir si el aviso "se entregó"). LINE es
        mejor esfuerzo: si falla o no está configurado, no afecta a ese valor
        ni bloquea nada, solo queda en el log.
        """
        entregado = self.telegram(chat_id, text)
        if self.line_token and self.line_to:
            self.line(self.line_to, _a_texto_plano(text))
        return entregado

    # ---- Telegram -----------------------------------------------------------
    def telegram(self, chat_id, text):
        """Envía a uno o varios chats (privados y/o grupos). True si todos OK."""
        ids = chat_ids(chat_id)
        if not self.tg_token or not ids:
            return False
        vivos = [c for c in ids if c not in self._muertos]
        if not vivos:
            return False
        # True si el aviso llegó a ALGÚN destino vivo. Antes bastaba con que un
        # grupo borrado fallase para dar por perdido un mensaje que sí había
        # llegado al chat personal, y eso despistaba en los registros.
        llego = False
        for cid in vivos:
            if self._send_one(cid, text):
                llego = True
        return llego

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
                permanente = r.status_code in (400, 403) and any(
                    m in r.text for m in ("chat was deleted", "bot was kicked",
                                          "bot was blocked", "chat not found",
                                          "user is deactivated"))
                if permanente and str(chat_id) not in self._muertos:
                    self._muertos.add(str(chat_id))
                    print("  [telegram] el destino %s ya no existe; dejo de "
                          "escribirle (quítalo de TELEGRAM_CHAT_ID)" % chat_id)
                elif not permanente:
                    print("  [telegram] %s: %s" % (r.status_code, r.text[:200]))
            return r.ok
        except Exception as e:
            # Nunca volcar la excepción tal cual: algunas (ConnectionError,
            # Timeout) incluyen la URL completa, y esa URL lleva el token del
            # bot embebido (.../bot<TOKEN>/sendMessage). Esto puede acabar en
            # un log público de GitHub Actions.
            msg = re.sub(re.escape(self.tg_token), "***", str(e)) if self.tg_token else str(e)
            print("  [telegram] error:", msg)
            return False

    # ---- LINE -----------------------------------------------------------------
    def line(self, to, text):
        """Envía a uno o varios destinos de LINE (userId o groupId). True si
        todos OK. Requiere LINE_CHANNEL_ACCESS_TOKEN (canal Messaging API) y
        que el destino haya añadido esa cuenta como amiga (o la haya metido
        en el grupo)."""
        destinos = chat_ids(to)
        if not self.line_token or not destinos:
            return False
        # LINE no entiende HTML; si llega texto con <b>/<a href> (porque se
        # llamó directo en vez de por avisar()), se convierte igual.
        if "<" in text:
            text = _a_texto_plano(text)
        # Límite real de LINE por mensaje de texto.
        text = text[:4900]
        llego = False
        for dest in destinos:
            if self._send_one_line(dest, text):
                llego = True
        return llego

    def _send_one_line(self, to, text):
        try:
            r = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": "Bearer " + self.line_token,
                        "Content-Type": "application/json"},
                json={"to": to, "messages": [{"type": "text", "text": text}]},
                timeout=20,
            )
            if not r.ok:
                print("  [line] %s: %s" % (r.status_code, r.text[:200]))
            return r.ok
        except Exception as e:
            msg = re.sub(re.escape(self.line_token), "***", str(e)) if self.line_token else str(e)
            print("  [line] error:", msg)
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
                check=False, timeout=15,
            )
            for _ in range(3):
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"],
                               check=False, timeout=15)
            subprocess.run(
                ["say", "¡Hay billetes disponibles! ¡Corre a comprar!"],
                check=False, timeout=20,
            )
        except Exception as e:
            print("  [mac] error:", e)

    def browser(self, url):
        if not self.open_browser or not url or not IS_MAC:
            return
        try:
            subprocess.run(["open", url], check=False, timeout=15)
        except Exception:
            pass
