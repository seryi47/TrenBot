"""Motor de vigilancia: recorre la watchlist, sondea proveedores y dispara avisos."""

import datetime as _dt
import json
import os
import threading
import time
from typing import List, Optional

from botviajes.models import Offer
from botviajes.providers import get_provider


# Panel web donde se ve todo junto; se enlaza en cada aviso de Telegram.
WEB_URL = os.environ.get("WEB_URL", "https://viaje-octubre.vercel.app").strip()


DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(iso):
    """'2026-10-11' -> 'domingo 11 de octubre'."""
    try:
        d = _dt.date.fromisoformat(iso)
        return "%s %d de %s" % (DIAS_ES[d.weekday()], d.day, MESES_ES[d.month - 1])
    except Exception:
        return iso


def bloque_horas(oferta, fecha):
    """Salida y llegada SIEMPRE visibles, dejando claro que la hora de salida
    es la del país desde el que despega (en una vuelta no es la de España)."""
    raw = oferta.raw or {}
    po = raw.get("pais_origen") or ""
    pd = raw.get("pais_destino") or ""
    aprox = "≈" if raw.get("llegada_estimada") else ""
    lineas = ["🛫 <b>Sale de %s el %s a las %s</b>%s" % (
        oferta.origin, fecha_larga(fecha), oferta.departure,
        (" — hora local de %s" % po) if po else "")]
    if oferta.arrival:
        lineas.append("🛬 Llega a %s a las %s%s%s" % (
            oferta.destination, aprox, oferta.arrival,
            (" — hora local de %s" % pd) if pd else ""))
    return lineas


def _norm_time(t):
    return (t or "").strip().replace(".", ":")


class Engine:
    def __init__(self, notifier, poll_interval=30, alert_interval=10,
                 default_chat_id=None, state_file="watches.json", max_alerts=120,
                 historial_file="historico.json"):
        self.notifier = notifier
        self.poll_interval = poll_interval      # cada cuánto se consulta al proveedor (s)
        self.alert_interval = alert_interval    # cada cuánto se reenvía el aviso (s)
        self.default_chat_id = default_chat_id
        self.state_file = state_file
        self.max_alerts = max_alerts            # tope de avisos seguidos antes de pausar el spam
        self._lock = threading.RLock()
        self.watches = []                       # lista de dicts (persistente)
        self._state = {}                        # estado runtime por watch id (no persistente)
        self._stop = threading.Event()
        self.paused = False                     # /pausa: no sondea ni avisa, sigue escuchando
        self.historial_cambiado = False         # ¿hay precios nuevos que publicar?
        self.shutdown_requested = False         # /apagar: el bucle debe terminar
        # El histórico de precios va en su propio fichero SIN datos personales,
        # para poder subirlo al repo: así el bot de la nube no pierde la memoria
        # de precios cada vez que GitHub releva el job (cada ~5 h).
        self.historial_file = historial_file
        self.historial = {}
        self._load()
        self._cargar_historial()

    # ---- persistencia -------------------------------------------------------
    def _load(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as fh:
                    self.watches = json.load(fh)
            except Exception as e:
                print("[engine] no se pudo leer %s: %s" % (self.state_file, e))

    def _save(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as fh:
                json.dump(self.watches, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[engine] no se pudo guardar %s: %s" % (self.state_file, e))

    # ---- histórico de precios (compartido con la web y con la nube) ---------
    @staticmethod
    def clave_historial(watch):
        return "%s|%s|%s|%s" % (watch["providers"][0], watch["origin"],
                                watch["destination"], watch["date"])

    def _cargar_historial(self):
        if os.path.exists(self.historial_file):
            try:
                with open(self.historial_file, "r", encoding="utf-8") as fh:
                    self.historial = json.load(fh)
            except Exception as e:
                print("[engine] no se pudo leer %s: %s" % (self.historial_file, e))
        for w in self.watches:
            self._hidratar(w)

    def _hidratar(self, watch):
        """Le devuelve a una ruta el histórico que ya se conocía.

        Hay que hacerlo también al CREAR la ruta: en la nube no existe
        watches.json, así que las rutas nacen de watches.yaml DESPUÉS de leer el
        histórico. Sin esto arrancaban sin memoria y el primer guardado se
        cargaba todo lo acumulado.
        """
        serie = self.historial.get(self.clave_historial(watch))
        if serie:
            watch["serie"] = [list(x) for x in serie]
            if watch.get("ultimo_precio") is None:
                watch["ultimo_precio"] = serie[-1][1]
            if not watch.get("ultimo_visto"):
                watch["ultimo_visto"] = serie[-1][0]

    def _guardar_historial(self):
        try:
            with open(self.historial_file, "w", encoding="utf-8") as fh:
                json.dump(self.historial, fh, ensure_ascii=False, indent=1)
        except Exception as e:
            print("[engine] no se pudo guardar %s: %s" % (self.historial_file, e))

    # ---- gestión de watches -------------------------------------------------
    def add_watch(self, name, providers, origin, destination, date,
                  time_="", max_price=None, chat_id=None, adults=1,
                  poll_interval=None):
        with self._lock:
            wid = (max([w["id"] for w in self.watches], default=0) + 1)
            watch = {
                "id": wid, "name": name or ("%s→%s" % (origin, destination)),
                "providers": [p.lower() for p in providers],
                "origin": origin, "destination": destination, "date": date,
                "time": _norm_time(time_), "max_price": max_price,
                "chat_id": chat_id, "enabled": True,
                # Los vuelos hay que sondearlos MUY despacio: Ryanair y Wizz
                # cortan con 429/503 si se les insiste. 600-1800 s es lo sano.
                "adults": int(adults or 1), "poll_interval": poll_interval,
            }
            self._hidratar(watch)
            self.watches.append(watch)
            self._save()
            return watch

    def remove_watch(self, wid):
        with self._lock:
            before = len(self.watches)
            self.watches = [w for w in self.watches if w["id"] != int(wid)]
            self._state.pop(int(wid), None)
            self._save()
            return len(self.watches) < before

    def list_watches(self):
        with self._lock:
            return list(self.watches)

    def set_paused(self, value):
        """/pausa y /seguir: deja de consultar a los operadores (y de avisar)
        sin matar el proceso, para poder reanudar desde Telegram."""
        with self._lock:
            self.paused = bool(value)
            if self.paused:
                self._state.clear()   # al reanudar, vuelve a avisar de lo que haya
            return self.paused

    def request_shutdown(self):
        """/apagar: pide al bucle que termine del todo."""
        self.shutdown_requested = True
        self._stop.set()

    def silence_all(self):
        """/stop: calla los avisos que estén sonando (sin dejar de vigilar)."""
        with self._lock:
            n = 0
            for st in self._state.values():
                if st.get("firing") and not st.get("silenced"):
                    st["silenced"] = True
                    n += 1
            return n

    def seed_from_config(self, config_watches):
        """Carga watches definidos en config.yaml (sin duplicar por nombre)."""
        with self._lock:
            existing = {w["name"] for w in self.watches}
            for cw in (config_watches or []):
                if cw.get("name") in existing:
                    continue
                self.add_watch(
                    name=cw.get("name"),
                    providers=cw.get("providers") or ["renfe"],
                    origin=cw["origin"], destination=cw["destination"],
                    date=cw["date"], time_=cw.get("time", ""),
                    max_price=cw.get("max_price"), chat_id=cw.get("chat_id"),
                    adults=cw.get("adults", 1),
                    poll_interval=cw.get("poll_interval"),
                )

    # ---- lógica de coincidencia --------------------------------------------
    def _matches(self, offer: Offer, watch) -> bool:
        if not offer.available:
            return False
        wt = watch.get("time")
        if wt and _norm_time(offer.departure) != wt:
            return False
        if offer.price is not None and offer.price <= 0:
            return False        # 0 € no existe: es un precio que no llegó
        mp = watch.get("max_price")
        if mp is not None and (offer.price is None or offer.price > float(mp)):
            return False
        return True

    def _poll(self, watch):
        """Devuelve (las_que_cumplen, todas). La segunda lista sirve para seguir
        el precio aunque aun no haya bajado del tope."""
        found, todas = [], []
        for pname in watch["providers"]:
            try:
                provider = get_provider(pname)
                offers = provider.search(watch["origin"], watch["destination"],
                                         watch["date"], adults=watch.get("adults", 1))
                todas.extend(offers)
                found.extend([o for o in offers if self._matches(o, watch)])
            except NotImplementedError:
                pass  # proveedor experimental (p.ej. iryo)
            except Exception as e:
                print("  [%s] error en '%s': %s" % (pname, watch["name"], e))
        return found, todas

    # ---- seguimiento de precio ---------------------------------------------
    @staticmethod
    def _mas_barata(offers, hora=None):
        """La oferta más barata. Si la ruta vigila una salida concreta, solo
        cuenta esa: si no, un día con varios vuelos guardaría el precio de otro
        vuelo distinto del que se está siguiendo."""
        # Un importe de 0 o negativo nunca es una tarifa real: es que el
        # proveedor no la ha dado. Se descarta pase lo que pase.
        con_precio = [o for o in offers
                      if o.available and o.price is not None and o.price > 0]
        if hora:
            exactas = [o for o in con_precio if _norm_time(o.departure) == _norm_time(hora)]
            con_precio = exactas or []
        return min(con_precio, key=lambda o: o.price) if con_precio else None

    def _registrar_precio(self, watch, todas):
        """Guarda el precio mas barato visto y avisa si ha BAJADO.

        Devuelve el texto del aviso de bajada, o None. El umbral evita que un
        redondeo del cambio de divisa dispare una alerta falsa.
        """
        mejor = self._mas_barata(todas, watch.get("time"))
        if mejor is None:
            # Puede que el proveedor solo haya dado un precio orientativo (Wizz
            # a veces responde "míralo en la web"). Se guarda aparte para que la
            # vigilancia no se quede ciega, pero NO cuenta como precio real ni
            # dispara ningún aviso.
            orient = [o for o in todas
                      if (o.raw or {}).get("orientativo") and o.price and o.price > 0]
            if orient:
                with self._lock:
                    watch["ultimo_orientativo"] = min(o.price for o in orient)
                    watch["orientativo_visto"] = time.strftime("%Y-%m-%d %H:%M")
                    self._save()
            return None
        anterior = watch.get("ultimo_precio")
        umbral = float(watch.get("umbral_bajada", 3.0))
        # Los vuelos que salen de fuera de la zona euro cotizan en su moneda
        # (Pardubice en coronas). Si la tarifa no se ha movido pero sí el tipo
        # de cambio del BCE, el precio en euros baila unos céntimos y ensuciaría
        # la serie. Se compara en la moneda original cuando se conoce.
        bruto = (mejor.raw or {}).get("bruto")
        divisa = (mejor.raw or {}).get("divisa")
        if (divisa and divisa != "EUR" and bruto is not None
                and watch.get("ultimo_bruto") is not None
                and watch.get("ultimo_divisa") == divisa
                and abs(float(bruto) - float(watch["ultimo_bruto"])) < 0.01):
            return None      # misma tarifa, solo se movió el cambio
        aviso = None
        if (watch.get("avisar_bajadas", True) and anterior is not None
                and mejor.price <= anterior - umbral):
            aviso = self._texto_bajada(watch, mejor, anterior)
        if anterior is None or abs(mejor.price - anterior) >= 0.01:
            with self._lock:
                # Serie propia: sin ella el aviso no puede decir si el precio
                # está barato o solo rebotando dentro de una subida.
                serie = watch.setdefault("serie", [])
                serie.append([time.strftime("%Y-%m-%d %H:%M"), mejor.price])
                del serie[:-120]
                self.historial[self.clave_historial(watch)] = serie
                self._guardar_historial()
                self.historial_cambiado = True
                watch["ultimo_precio"] = mejor.price
                watch["ultimo_visto"] = time.strftime("%Y-%m-%d %H:%M")
                watch["ultimo_detalle"] = "%s %s %s" % (
                    mejor.departure, mejor.label, mejor.provider)
                watch["ultimo_url"] = mejor.buy_url
                watch["ultimo_salida"] = mejor.departure
                watch["ultimo_llegada"] = mejor.arrival
                watch["ultimo_etiqueta"] = mejor.label
                watch["ultimo_plazas"] = (mejor.raw or {}).get("plazas")
                watch["ultimo_bruto"] = bruto
                watch["ultimo_divisa"] = divisa
                self._save()
        return aviso

    def _texto_bajada(self, watch, oferta, anterior):
        """Aviso de bajada CON CONTEXTO.

        Un "ha bajado 4 €" a secas engaña: se lee como "está barato" cuando
        muchas veces es un rebote dentro de una subida. Por eso el aviso dice
        siempre si es mínimo histórico, entre qué precios se ha movido y cómo
        va respecto al primero que se vio.
        """
        previos = [p[1] for p in watch.get("serie", [])]
        # ¿es mínimo? se compara contra lo visto ANTES de esta lectura...
        es_minimo = (not previos) or oferta.price <= min(previos) + 0.01
        # ...pero el rango que se enseña sí incluye el precio de ahora, o el
        # titular diría "mínimo" y debajo aparecería otro número más bajo.
        serie = previos + [oferta.price]
        minimo, maximo, partida = min(serie), max(serie), serie[0]
        cabeza = ("🟢 <b>¡PRECIO MÍNIMO HASTA AHORA!</b>" if es_minimo
                  else "📉 <b>Ha bajado un poco</b>")
        lineas = [cabeza, "", "<b>%s</b>" % watch["name"]]
        lineas += bloque_horas(oferta, watch["date"])
        lineas += ["<i>%s %s</i>" % (oferta.provider.upper(), oferta.label), "",
                   "Antes: <s>%.2f €</s>   Ahora: <b>%.2f €</b>  (−%.2f €)"
                   % (anterior, oferta.price, anterior - oferta.price), ""]

        if previos:
            lineas.append("<i>Contexto:</i> lo más barato que he visto son "
                          "<b>%.2f €</b> y lo más caro %.2f €." % (minimo, maximo))
            dif = oferta.price - partida
            if abs(dif) >= 1:
                lineas.append("Respecto al primer día que lo vigilé (%.2f €) está "
                              "<b>%.2f € %s</b>." % (partida, abs(dif),
                                                     "por encima" if dif > 0 else "por debajo"))

        lineas += ["", "👉 <a href=\"%s\">Comprar en %s</a>"
                   % (oferta.buy_url, oferta.provider.title())]
        if WEB_URL:
            lineas.append("🌐 %s" % WEB_URL)
        return "\n".join(lineas)

    # ---- bucle --------------------------------------------------------------
    def _chat_for(self, watch):
        return watch.get("chat_id") or self.default_chat_id

    def _alert_text(self, watch, offers: List[Offer]):
        head = "🚨🎫 <b>¡BILLETES DISPONIBLES!</b> 🎫🚨"
        lines = [head, "", "<b>%s</b>" % watch["name"], ""]
        for o in offers:
            lines += bloque_horas(o, watch["date"])
            lines.append("💶 <b>%s</b> por persona · %s %s" %
                         (o.price_str(), o.provider.upper(), o.label))
        urls = sorted({o.buy_url for o in offers if o.buy_url})
        if urls:
            lines += [""] + ['👉 <a href="%s">Comprar</a>' % u for u in urls]
        if WEB_URL:
            lines += ["", "🌐 %s" % WEB_URL]
        return "\n".join(lines)

    def tick(self):
        now = time.time()
        if self.paused:
            return
        with self._lock:
            watches = list(self.watches)
        for watch in watches:
            if not watch.get("enabled", True):
                continue
            st = self._state.setdefault(watch["id"], {
                "last_poll": 0, "firing": False, "silenced": False,
                "alert_count": 0, "offers": [],
            })
            # ¿toca sondear al proveedor? (cada ruta puede llevar su propio ritmo)
            cada = watch.get("poll_interval") or self.poll_interval
            if now - st["last_poll"] >= cada:
                st["last_poll"] = now
                offers, todas = self._poll(watch)
                bajada = self._registrar_precio(watch, todas)
                if bajada:
                    entregado = self.notifier.telegram(self._chat_for(watch), bajada)
                    self.notifier.mac("Baja de precio", watch["name"])
                    print("[%s] 📉 BAJADA en '%s' -> aviso %s"
                          % (time.strftime("%H:%M:%S"), watch["name"],
                             "enviado" if entregado else "NO ENTREGADO"))
                if offers:
                    if not st["firing"]:
                        st["firing"] = True
                        st["silenced"] = False
                        st["alert_count"] = 0
                    st["offers"] = offers
                else:
                    st["firing"] = False
                    st["silenced"] = False
                    st["alert_count"] = 0
                    st["offers"] = []
                stamp = time.strftime("%H:%M:%S")
                print("[%s] %s -> %d ofertas con plaza" % (stamp, watch["name"], len(offers)))

            # ¿tocan avisos? (cada tick = alert_interval, mientras esté "firing")
            if st["firing"] and not st["silenced"] and st["offers"]:
                chat = self._chat_for(watch)
                text = self._alert_text(watch, st["offers"])
                self.notifier.telegram(chat, text)
                if st["alert_count"] == 0:
                    self.notifier.mac("¡Billetes disponibles!", watch["name"])
                    self.notifier.browser(st["offers"][0].buy_url)
                st["alert_count"] += 1
                if st["alert_count"] >= self.max_alerts:
                    st["silenced"] = True
                    self.notifier.telegram(chat,
                        "🔕 Pauso los avisos de <b>%s</b> (llevabas %d). Sigo vigilando; "
                        "te reavisaré si cambia." % (watch["name"], st["alert_count"]))

    def revisar(self, watch):
        """Una consulta suelta a una ruta, sin avisar por Telegram.

        Devuelve (las_que_cumplen, todas, texto_bajada_o_None) y deja
        registrado el precio, igual que hace el bucle normal. La usa
        `run.py --once` para inspeccionar sin montar el bucle.
        """
        coinciden, todas = self._poll(watch)
        return coinciden, todas, self._registrar_precio(watch, todas)

    def check_once(self):
        """Una sola pasada por toda la watchlist: envía UN aviso por ruta con plaza.

        Pensado para ejecuciones tipo cron (GitHub Actions), sin bucle ni estado.
        Devuelve cuántas rutas tienen plaza.
        """
        if self.paused:
            print("[%s] en pausa (/seguir para reanudar)" % time.strftime("%H:%M:%S"))
            return 0
        total = 0
        ahora = time.time()
        for watch in list(self.watches):
            if not watch.get("enabled", True):
                continue
            # Respeta el ritmo propio de la ruta: el bucle de Actions llama aquí
            # cada 60 s, pero un vuelo con poll_interval=900 solo se consulta
            # cada 15 min. Sin esto Ryanair y Wizz cortarían por exceso.
            cada = watch.get("poll_interval")
            st = self._state.setdefault(watch["id"], {"last_poll": 0})
            if cada and ahora - st.get("last_poll", 0) < cada:
                continue
            st["last_poll"] = ahora
            try:
                offers, todas = self._poll(watch)
                bajada = self._registrar_precio(watch, todas)
                if bajada:
                    entregado = self.notifier.telegram(self._chat_for(watch), bajada)
                    print("[%s] 📉 BAJADA en '%s' -> aviso %s"
                          % (time.strftime("%H:%M:%S"), watch["name"],
                             "enviado" if entregado else "NO ENTREGADO"))
            except Exception as e:
                print("  [%s] error: %s" % (watch["name"], e))
                continue
            stamp = time.strftime("%H:%M:%S")
            if offers:
                total += 1
                self.notifier.telegram(self._chat_for(watch), self._alert_text(watch, offers))
                print("[%s] %s -> %d con plaza (AVISO enviado)" %
                      (stamp, watch["name"], len(offers)))
            else:
                # En vuelos casi siempre HAY plaza: lo que pasa es que el precio
                # todavía no ha bajado al objetivo. Se dice tal cual.
                actual = watch.get("ultimo_precio")
                objetivo = watch.get("max_price")
                if actual is not None and objetivo is not None:
                    print("[%s] %s -> %.2f € (objetivo ≤%.0f €)"
                          % (stamp, watch["name"], actual, float(objetivo)))
                elif actual is not None:
                    print("[%s] %s -> %.2f €" % (stamp, watch["name"], actual))
                else:
                    print("[%s] %s -> sin plaza" % (stamp, watch["name"]))
        return total

    def run_forever(self):
        print("[engine] vigilando %d rutas | sondeo %ds | avisos %ds" %
              (len(self.watches), self.poll_interval, self.alert_interval))
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                print("[engine] error en tick:", e)
            self._stop.wait(self.alert_interval)

    def start_background(self):
        t = threading.Thread(target=self.run_forever, daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()
