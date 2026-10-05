"""Proveedor de mercado: lee Google Flights con un navegador.

Ryanair y Wizz tienen API propia y se consultan directamente. El resto de
compañías no, y a Bruselas-Zaventem (BRU) desde Alicante solo vuelan Transavia,
TUI fly, Vueling y Brussels Airlines. Para poder vigilarlas igualmente se lee
Google Flights, que las agrega a todas.

Dos cosas verificadas antes de fiarse de los números (05-oct-2026):

1. **Google da el precio TOTAL del grupo, no el de una persona.** Contrastado
   contra un vuelo de precio conocido: Ryanair ALC→CRL del 5-dic a las 18:05
   cuesta 106,99 € por persona; Google muestra 107 € pidiendo 1 adulto y 214 €
   pidiendo 2. Aquí se divide entre los pasajeros para dar siempre el precio
   por persona, como el resto de proveedores.
2. Skyscanner y Kiwi no se dejan (captcha y clave de API). Google Flights sí.

Limitaciones honestas: no da plazas restantes ni enlace de compra de la
aerolínea, y cada consulta tarda ~25 s porque hay que abrir un navegador.
"""

import re
from typing import List

from botviajes.models import Offer
from botviajes.providers.base import Provider

ESPERA_CARGA = 13000      # ms que tarda Google en pintar los resultados
COOKIES = ("button:has-text('Aceptar todo')", "button:has-text('Rechazar todo')")


class MercadoProvider(Provider):
    name = "mercado"

    def search(self, origin, destination, date, adults: int = 1) -> List[Offer]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [mercado] falta playwright; no puedo consultar el mercado")
            return []
        # Google a veces devuelve la página a medio pintar y salen menos vuelos
        # de los que hay. Eso bajaba el "más barato" a un vuelo caro, machacaba
        # el precio de referencia y en el siguiente sondeo parecía una BAJADA que
        # nunca ocurrió. Si la primera lectura sale pobre, se reintenta una vez.
        filas = self._leer(origin, destination, date, adults)
        if len(filas) < 2:
            import time as _t
            _t.sleep(4)
            otra = self._leer(origin, destination, date, adults)
            if len(otra) > len(filas):
                filas = otra
        url = self._url(origin, destination, date, adults)
        ofertas = []
        for sale, llega, cia, dur, total in filas:
            por_persona = round(total / max(adults, 1), 2)
            ofertas.append(Offer(
                provider=self.name, origin=origin, destination=destination,
                date=date, departure=sale, arrival=llega,
                label=cia, price=por_persona, available=True, buy_url=url,
                raw={"aerolinea": cia, "total_grupo": total, "pasajeros": adults,
                     "duracion": dur, "fuente": "google flights"}))
        return ofertas

    @staticmethod
    def _url(o, d, fecha, adults):
        return ("https://www.google.com/travel/flights?hl=es&curr=EUR&q="
                "Flights%%20to%%20%s%%20from%%20%s%%20on%%20%s%%20oneway"
                "%%20nonstop%%20for%%20%d%%20adults" % (d, o, fecha, adults))

    def _leer(self, o, d, fecha, adults):
        from playwright.sync_api import sync_playwright
        filas = []
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True,
                                  args=["--disable-blink-features=AutomationControlled"])
            try:
                ctx = b.new_context(
                    locale="es-ES", timezone_id="Europe/Madrid",
                    viewport={"width": 1500, "height": 1200},
                    user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/140.0.0.0 Safari/537.36"))
                ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
                pg = ctx.new_page()
                pg.goto(self._url(o, d, fecha, adults), timeout=90000,
                        wait_until="domcontentloaded")
                pg.wait_for_timeout(5000)
                for sel in COOKIES:
                    try:
                        if pg.locator(sel).first.is_visible(timeout=2000):
                            pg.locator(sel).first.click()
                            pg.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass
                pg.wait_for_timeout(ESPERA_CARGA)
                cuerpo = pg.inner_text("body")
                if "robot" in cuerpo.lower() or "unusual traffic" in cuerpo.lower():
                    print("  [mercado] Google nos ha pedido captcha; sin datos")
                    return []
                for fila in pg.locator("li").all():
                    try:
                        t = " ".join(fila.inner_text().split())
                    except Exception:
                        continue
                    leido = self._parsear(t, o, d)
                    if leido:
                        filas.append(leido)
            finally:
                b.close()
        # una misma compañía puede salir repetida; se deja la más barata de cada hora
        mejor = {}
        for sale, llega, cia, dur, total in filas:
            k = (sale, cia)
            if k not in mejor or total < mejor[k][4]:
                mejor[k] = (sale, llega, cia, dur, total)
        return sorted(mejor.values())

    @staticmethod
    def _parsear(t, o, d):
        """Una fila de resultado -> (salida, llegada, compañía, duración, total)."""
        if "€" not in t or len(t) > 260 or "%s–%s" % (o, d) not in t:
            return None
        horas = re.match(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})", t)
        if not horas:
            return None
        precio = re.search(r"(\d{1,3}(?:\.\d{3})?)\s*€", t)
        if not precio:
            return None
        # entre las horas y la duración está el nombre de la compañía
        cia = re.search(r"\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2}\s*(.+?)\s*\d+\s*h\s*\d*", t)
        dur = re.search(r"(\d+\s*h(?:\s*\d+\s*min)?)", t)
        return ("%02d:%s" % (int(horas.group(1).split(":")[0]), horas.group(1).split(":")[1]),
                "%02d:%s" % (int(horas.group(2).split(":")[0]), horas.group(2).split(":")[1]),
                (cia.group(1).strip() if cia else "?")[:28],
                dur.group(1) if dur else "",
                float(precio.group(1).replace(".", "")))
