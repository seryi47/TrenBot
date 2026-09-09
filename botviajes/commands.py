"""Lógica de comandos de Telegram, compartida por bot.py (local) y el bucle de Actions.

`handle_text` interpreta un comando y muta la watchlist del motor; devuelve
(texto_de_respuesta, watchlist_cambiada).
"""

from datetime import datetime, timedelta

import requests


def ayuda():
    """Texto de /ayuda. Es una función y no una constante para que las fechas de
    los ejemplos sean siempre futuras: si se quedan en el pasado, quien las copie
    se pone a vigilar un tren que ya salió."""
    d1 = (datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")
    d2 = (datetime.now() + timedelta(days=21)).strftime("%d/%m/%Y")
    return (
        "🚆✈️ <b>BotViajes</b>\n\n"
        "Vigila billetes y te avisa en cuanto hay plazas.\n\n"
        "<b>Añadir vigilancia</b> (campos separados por <code>;</code>):\n"
        "<code>/vigilar proveedores; origen; destino; fecha; [hora]; [precio_max]</code>\n\n"
        "Ejemplos:\n"
        "<code>/vigilar renfe; Alicante; Albacete; %s; 16:55</code>\n"
        "<code>/vigilar trenes; Madrid; Valencia; %s; ; 30</code>\n"
        "<code>/vigilar vuelos; ALC; BTS; %s; ; 60; 2</code>\n\n"
        "• proveedores: <code>renfe</code>, <code>ouigo</code>, <code>iryo</code>, "
        "<code>ryanair</code>, <code>wizz</code>, o los atajos <code>trenes</code> "
        "y <code>vuelos</code>\n"
        "• hora vacía = cualquier salida; precio_max y nº de pasajeros opcionales\n"
        "• en vuelos el precio es <b>por persona</b> y te aviso también cuando "
        "<b>baja</b>, aunque no llegue al tope\n\n"
        "<b>Otros:</b>\n"
        "/lista — ver vigilancias\n"
        "/precios — últimos precios de cada tramo\n"
        "/estado — ¿estoy vigilando o en pausa?\n"
        "/borrar &lt;id&gt; — quitar una\n"
        "/callar — callar los avisos que suenan (sigo vigilando)\n\n"
        "<b>Pararme:</b>\n"
        "/pausa — dejo de vigilar y de avisar, pero sigo aquí\n"
        "  (<code>/stop</code> y <code>/parar</code> hacen lo mismo)\n"
        "/seguir — vuelvo a vigilar\n"
        "/apagar — me apago del todo (te pediré confirmación; luego solo se "
        "reactiva desde el ordenador)\n" % (d1, d2, d2)
    )


def expand_providers(s):
    s = s.strip().lower()
    if s in ("trenes", "tren"):
        return ["renfe", "ouigo", "iryo"]
    if s in ("vuelos", "vuelo", "aviones", "avion"):
        return ["ryanair", "wizz"]
    if s in ("all", "todo", "todos"):
        return ["renfe", "ouigo", "iryo", "ryanair", "wizz"]
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
        return ayuda(), False

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
            adults = int(parts[6]) if len(parts) > 6 and parts[6] else 1
        except Exception as e:
            return "❌ Error: %s" % e, False
        # En vuelos hay que ir despacio: Ryanair y Wizz cortan si se les insiste.
        es_vuelo = any(p in ("ryanair", "wizz", "amadeus") for p in providers)
        w = engine.add_watch(
            name="%s→%s %s" % (origin, destination, time_ or ""),
            providers=providers, origin=origin, destination=destination,
            date=date, time_=time_, max_price=max_price,
            # el aviso vuelve al chat donde se creó la vigilancia: si el comando
            # llega de un grupo, el grupo entero recibe la alerta
            chat_id=str(chat_id) if chat_id else None,
            adults=adults, poll_interval=900 if es_vuelo else None,
        )
        reply = ("✅ Vigilando <b>#%s</b>: %s→%s el %s %s\nProveedores: %s%s\n\n"
                 "Te aviso aquí en cuanto haya plazas." %
                 (w["id"], origin, destination, parts[3], time_ or "(cualquier hora)",
                  ", ".join(providers),
                  ("\nPrecio máx: %.2f €" % max_price) if max_price else "")
                 + ("\nPasajeros: %d · sondeo cada 15 min" % adults if es_vuelo else ""))
        return reply, True

    if cmd == "lista":
        ws = engine.list_watches()
        if not ws:
            return "No hay vigilancias. Añade una con /vigilar (mira /ayuda).", False
        lines = ["<b>Vigilancias activas:</b>" if not engine.paused
                 else "<b>Vigilancias (⏸️ EN PAUSA — /seguir para reanudar):</b>"]
        for w in ws:
            ultimo = ("| ahora <b>%.2f€</b>" % w["ultimo_precio"]
                      if w.get("ultimo_precio") is not None else "")
            lines.append("#%s — %s→%s | %s %s | %s%s %s" % (
                w["id"], w["origin"], w["destination"], w["date"],
                w.get("time") or "(cualquiera)", ", ".join(w["providers"]),
                ("| ≤%.0f€" % w["max_price"]) if w.get("max_price") else "", ultimo))
        return "\n".join(lines), False

    if cmd in ("precios", "precio"):
        ws = engine.list_watches()
        conocidos = [w for w in ws if w.get("ultimo_precio") is not None]
        if not conocidos:
            return ("Todavía no tengo ningún precio. En cuanto haga la primera "
                    "consulta aparecerán aquí."), False
        lineas = ["💶 <b>Últimos precios vistos</b> (por persona)", ""]
        total = 0.0
        for w in sorted(conocidos, key=lambda x: x["id"]):
            objetivo = ("  objetivo ≤%.0f€" % w["max_price"]) if w.get("max_price") else ""
            lineas.append("#%s <b>%s</b>\n   <b>%.2f €</b>  %s%s\n   <i>visto %s</i>" % (
                w["id"], w["name"], w["ultimo_precio"],
                w.get("ultimo_detalle", ""), objetivo, w.get("ultimo_visto", "?")))
            total += w["ultimo_precio"]
        lineas += ["", "Suma de todos los tramos vigilados: <b>%.2f €</b>" % total]
        return "\n".join(lineas), False

    if cmd == "borrar":
        if not rest.isdigit():
            return "Uso: <code>/borrar &lt;id&gt;</code> (mira /lista)", False
        ok = engine.remove_watch(int(rest))
        return ("🗑️ Borrada #%s" % rest if ok else "No encontré la #%s" % rest), ok

    if cmd in ("callar", "silencio"):
        n = engine.silence_all()
        return "🔕 Avisos callados (%d). Sigo vigilando y te reavisaré si cambia." % n, False

    # /stop hace lo que la gente espera: parar. Callar los avisos es /callar.
    if cmd in ("pausa", "pausar", "parar", "stop"):
        if engine.paused:
            return "⏸️ Ya estaba en pausa. /seguir para reanudar.", False
        engine.set_paused(True)
        return ("⏸️ <b>En pausa.</b> Dejo de consultar a los operadores y no te aviso.\n"
                "Sigo aquí escuchando: /seguir para reanudar.\n\n"
                "<i>Si lo que querías era solo callar un aviso que estaba sonando, "
                "eso es /callar.</i>"), True

    if cmd in ("seguir", "reanudar", "continuar"):
        if not engine.paused:
            return "▶️ Ya estaba vigilando. /estado para ver los detalles.", False
        engine.set_paused(False)
        return "▶️ <b>Vigilando otra vez.</b> Te aviso en cuanto haya plaza.", True

    if cmd == "estado":
        ws = [w for w in engine.list_watches() if w.get("enabled", True)]
        estado = "⏸️ en pausa" if engine.paused else "▶️ vigilando"
        # Cada ruta puede llevar su propio ritmo (los vuelos van mucho más
        # despacio que los trenes), así que decir solo el general engaña.
        ritmos = sorted({int(w.get("poll_interval") or engine.poll_interval) for w in ws})
        def bonito(s):
            return "%d min" % (s // 60) if s >= 60 else "%d s" % s
        return ("<b>Estado:</b> %s\nRutas vigiladas: %d\n"
                "Sondeo: cada %s\n\n%s"
                % (estado, len(ws), " y cada ".join(bonito(r) for r in ritmos),
                   "/seguir para reanudar" if engine.paused else "/pausa para pararme")), False

    if cmd == "apagar":
        if rest.strip().lower() not in ("si", "sí", "confirmar"):
            return ("⚠️ <b>/apagar</b> me apaga del todo y <b>no podrás reactivarme "
                    "desde Telegram</b> (habría que hacerlo desde el ordenador).\n\n"
                    "Si solo quieres que deje de avisarte, usa <b>/pausa</b> — esa sí "
                    "se deshace con /seguir.\n\n"
                    "Para apagarme de verdad: <code>/apagar si</code>"), False
        engine.request_shutdown()
        return "🔌 <b>Apagándome.</b> Hasta luego. Para volver: <code>gh workflow enable vigilar.yml</code>", False

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
