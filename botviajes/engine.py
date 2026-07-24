"""Motor de vigilancia: recorre la watchlist, sondea proveedores y dispara avisos."""

import json
import os
import threading
import time
from typing import List, Optional

from botviajes.models import Offer
from botviajes.providers import get_provider


def _norm_time(t):
    return (t or "").strip().replace(".", ":")


class Engine:
    def __init__(self, notifier, poll_interval=30, alert_interval=10,
                 default_chat_id=None, state_file="watches.json", max_alerts=120):
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
        self._load()

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

    # ---- gestión de watches -------------------------------------------------
    def add_watch(self, name, providers, origin, destination, date,
                  time_="", max_price=None, chat_id=None):
        with self._lock:
            wid = (max([w["id"] for w in self.watches], default=0) + 1)
            watch = {
                "id": wid, "name": name or ("%s→%s" % (origin, destination)),
                "providers": [p.lower() for p in providers],
                "origin": origin, "destination": destination, "date": date,
                "time": _norm_time(time_), "max_price": max_price,
                "chat_id": chat_id, "enabled": True,
            }
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
                )

    # ---- lógica de coincidencia --------------------------------------------
    def _matches(self, offer: Offer, watch) -> bool:
        if not offer.available:
            return False
        wt = watch.get("time")
        if wt and _norm_time(offer.departure) != wt:
            return False
        mp = watch.get("max_price")
        if mp is not None and (offer.price is None or offer.price > float(mp)):
            return False
        return True

    def _poll(self, watch) -> List[Offer]:
        found = []
        for pname in watch["providers"]:
            try:
                provider = get_provider(pname)
                offers = provider.search(watch["origin"], watch["destination"], watch["date"])
                found.extend([o for o in offers if self._matches(o, watch)])
            except NotImplementedError:
                pass  # proveedor experimental (p.ej. iryo)
            except Exception as e:
                print("  [%s] error en '%s': %s" % (pname, watch["name"], e))
        return found

    # ---- bucle --------------------------------------------------------------
    def _chat_for(self, watch):
        return watch.get("chat_id") or self.default_chat_id

    def _alert_text(self, watch, offers: List[Offer]):
        head = "🚨🎫 <b>¡BILLETES DISPONIBLES!</b> 🎫🚨"
        lines = [head, "", "<b>%s</b>" % watch["name"], "Fecha: %s" % watch["date"], ""]
        for o in offers:
            arr = (" → %s" % o.arrival) if o.arrival else ""
            lines.append("• <b>%s</b>%s | %s | %s | %s" %
                         (o.departure, arr, o.label, o.price_str(), o.provider.upper()))
        urls = sorted({o.buy_url for o in offers if o.buy_url})
        if urls:
            lines += [""] + ["👉 %s" % u for u in urls]
        return "\n".join(lines)

    def tick(self):
        now = time.time()
        with self._lock:
            watches = list(self.watches)
        for watch in watches:
            if not watch.get("enabled", True):
                continue
            st = self._state.setdefault(watch["id"], {
                "last_poll": 0, "firing": False, "silenced": False,
                "alert_count": 0, "offers": [],
            })
            # ¿toca sondear al proveedor?
            if now - st["last_poll"] >= self.poll_interval:
                st["last_poll"] = now
                offers = self._poll(watch)
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

    def check_once(self):
        """Una sola pasada por toda la watchlist: envía UN aviso por ruta con plaza.

        Pensado para ejecuciones tipo cron (GitHub Actions), sin bucle ni estado.
        Devuelve cuántas rutas tienen plaza.
        """
        total = 0
        for watch in list(self.watches):
            if not watch.get("enabled", True):
                continue
            try:
                offers = self._poll(watch)
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
