"""Lógica de comandos de Telegram, compartida por bot.py (local) y el bucle de Actions.

`handle_text` interpreta un comando y muta la watchlist del motor; devuelve
(texto_de_respuesta, watchlist_cambiada).
"""

from datetime import datetime

import requests

AYUDA = (
    "🚆✈️ <b>BotViajes</b>\n\n"
    "Vigila billetes y te avisa en cuanto hay plazas.\n\n"
    "<b>Añadir vigilancia</b> (campos separados por <code>;</code>):\n"
    "<code>/vigilar proveedores; origen; destino; fecha; [hora]; [precio_max]</code>\n\n"
    "Ejemplos:\n"
    "<code>/vigilar renfe; Alicante; Albacete; 24/07/2026; 16:55</code>\n"
    "<code>/vigilar trenes; Madrid; Valencia; 10/08/2026; ; 30</code>\n\n"
    "• proveedores: <code>renfe</code>, <code>ouigo</code>, <code>iryo</code>, "
    "<code>amadeus</code>, o <code>trenes</code>\n"
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


def handle_text(text, chat_id, engine):
    """Devuelve (respuesta:str|None, cambiada:bool)."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return None, False
    cmd, _, rest = text.partition(" ")
    cmd = cmd.lstrip("/").lower().split("@")[0]  # admite /cmd@BotName
    rest = rest.strip()

    if cmd in ("start", "ayuda", "help"):
        return AYUDA, False

    if cmd == "vigilar":
        parts = [p.strip() for p in rest.split(";")]
        if len(parts) < 4:
            return ("Formato:\n<code>/vigilar proveedores; origen; destino; fecha; "
                    "[hora]; [precio_max]</code>\n\nMira /ayuda para ejemplos."), False
        try:
            providers = expand_providers(parts[0])
            origin, destination = parts[1], parts[2]
            date = to_iso(parts[3])
            time_ = parts[4] if len(parts) > 4 else ""
            max_price = float(parts[5].replace(",", ".")) if len(parts) > 5 and parts[5] else None
        except Exception as e:
            return "❌ Error: %s" % e, False
        w = engine.add_watch(
            name="%s→%s %s" % (origin, destination, time_ or ""),
            providers=providers, origin=origin, destination=destination,
            date=date, time_=time_, max_price=max_price, chat_id=None,
        )
        reply = ("✅ Vigilando <b>#%s</b>: %s→%s el %s %s\nProveedores: %s%s\n\n"
                 "Te aviso aquí en cuanto haya plazas." %
                 (w["id"], origin, destination, parts[3], time_ or "(cualquier hora)",
                  ", ".join(providers),
                  ("\nPrecio máx: %.2f €" % max_price) if max_price else ""))
        return reply, True

    if cmd == "lista":
        ws = engine.list_watches()
        if not ws:
            return "No hay vigilancias. Añade una con /vigilar (mira /ayuda).", False
        lines = ["<b>Vigilancias activas:</b>"]
        for w in ws:
            lines.append("#%s — %s→%s | %s %s | %s%s" % (
                w["id"], w["origin"], w["destination"], w["date"],
                w.get("time") or "(cualquiera)", ", ".join(w["providers"]),
                ("| ≤%.0f€" % w["max_price"]) if w.get("max_price") else ""))
        return "\n".join(lines), False

    if cmd == "borrar":
        if not rest.isdigit():
            return "Uso: <code>/borrar &lt;id&gt;</code> (mira /lista)", False
        ok = engine.remove_watch(int(rest))
        return ("🗑️ Borrada #%s" % rest if ok else "No encontré la #%s" % rest), ok

    if cmd == "stop":
        n = engine.silence_all()
        return "🔕 Avisos callados (%d). Sigo vigilando y te reavisaré si cambia." % n, False

    return "Comando no reconocido. Mira /ayuda.", False


# ---- Telegram getUpdates (para el bucle sin webhook) -----------------------
def get_updates(token, offset=None, timeout=20):
    """Long-poll de mensajes nuevos. Devuelve (lista_updates, nuevo_offset)."""
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    r = requests.get("https://api.telegram.org/bot%s/getUpdates" % token,
                     params=params, timeout=timeout + 15)
    r.raise_for_status()
    data = r.json()
    updates = data.get("result", [])
    new_offset = offset
    for u in updates:
        new_offset = u["update_id"] + 1
    return updates, new_offset
