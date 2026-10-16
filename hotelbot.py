#!/usr/bin/env python3
"""HotelBot: vigila precios de hoteles en Booking.com para Shanghái.

Viaje: 14->20 dic 2026, 6 noches, 2 personas, habitación doble con baño
privado (sin camas compartidas ni dormitorios). Zonas: Jing'an, People's
Square, West Nanjing Road, Xintiandi/Concesión Francesa. Tope: 150 €/persona
(300 € los dos) por la estancia completa — con los precios de hoy todo cabe
de sobra, así que el aviso es de BAJADAS y de HOTELES NUEVOS que aparezcan
en la búsqueda, no de "cabe en el tope".

Booking no tiene API pública para esto: se lee con Playwright + huella de
Chrome, misma técnica que botviajes/providers/mercado.py para Google Flights.
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

from botviajes.notifier import Notifier

CHECKIN = "2026-12-14"
CHECKOUT = "2026-12-20"
ADULTOS = 2
HISTORICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hoteles_historico.json")
UMBRAL = 1.0  # € de bajada mínima para que merezca un aviso

ZONAS = [
    ("Jing'an", "Jing%27an%2C+Shanghai"),
    ("People's Square", "People%27s+Square%2C+Shanghai"),
    ("West Nanjing Road", "West+Nanjing+Road%2C+Shanghai"),
    ("Xintiandi / Concesión Francesa", "Xintiandi%2C+Shanghai"),
]


def _url(q):
    # selected_currency fuerza euros: sin esto, Booking decide la divisa por
    # la IP (en la nube de GitHub sirve US$, no €, y el regex de precio no
    # casaba nunca -> 0 hoteles encontrados aunque las tarjetas sí cargaban).
    return ("https://www.booking.com/searchresults.es.html?ss=%s"
            "&checkin=%s&checkout=%s&group_adults=%d&no_rooms=1&group_children=0"
            "&order=price&selected_currency=EUR" % (q, CHECKIN, CHECKOUT, ADULTOS))


def buscar_zona(pg, q):
    pg.goto(_url(q), timeout=60000, wait_until="domcontentloaded")
    pg.wait_for_timeout(5000)
    try:
        sel = pg.locator("#onetrust-accept-btn-handler")
        if sel.first.is_visible(timeout=1500):
            sel.first.click()
            pg.wait_for_timeout(3000)
    except Exception:
        pass
    pg.wait_for_timeout(5000)
    tarjetas = pg.locator('[data-testid="property-card"]').all()
    if os.environ.get("HOTELBOT_DEBUG"):
        print("    [debug] título: %r | url final: %s | tarjetas: %d"
              % (pg.title(), pg.url, len(tarjetas)))
        if tarjetas:
            print("    [debug] texto 1a tarjeta: %r"
                  % (" ".join(tarjetas[0].inner_text().split())[:300]))
        else:
            print("    [debug] primeros 300 chars body: %r"
                  % (" ".join(pg.inner_text("body").split())[:300]))
    out = []
    dorms = 0
    sin_match = []
    for c in tarjetas:
        try:
            t = " ".join(c.inner_text().split())
        except Exception:
            continue
        # Fuera dormitorios y camas compartidas: el viaje es habitación
        # privada para los dos, no compartir con desconocidos.
        if re.search(r"(?i)compartid|dormitorio", t):
            dorms += 1
            continue
        m = re.search(r"Se abre en una ventana nueva(.*?)\d noches, \d adultos € ([\d.,]+) Precio", t)
        if not m:
            if os.environ.get("HOTELBOT_DEBUG") and len(sin_match) < 3:
                sin_match.append(t[:300])
            continue
        nombre = t.split(" Se abre")[0].strip()
        href = None
        try:
            href = c.locator("a").first.get_attribute("href")
        except Exception:
            pass
        out.append({"nombre": nombre, "total": float(m.group(2).replace(".", "").replace(",", ".")),
                    "url": href})
    if os.environ.get("HOTELBOT_DEBUG"):
        print("    [debug] tarjetas=%d dorms=%d privadas_ok=%d privadas_sin_match=%d"
              % (len(tarjetas), dorms, len(out), len(sin_match)))
        for s in sin_match:
            print("    [debug] sin match: %r" % s)
    return out


def main():
    try:
        with open(HISTORICO, encoding="utf-8") as fh:
            historico = json.load(fh)
    except Exception:
        historico = {}

    notifier = Notifier(mac_alerts=False, open_browser=False)
    destino = os.environ.get("TELEGRAM_CHAT_ID", "")
    avisos = []
    vistos = 0

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(locale="es-ES", timezone_id="Europe/Madrid",
                            viewport={"width": 1500, "height": 1300},
                            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/140.0.0.0 Safari/537.36"))
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        pg = ctx.new_page()
        for zona, q in ZONAS:
            try:
                hoteles = buscar_zona(pg, q)
            except Exception as e:
                print("  [%s] error: %s" % (zona, str(e)[:120]))
                continue
            print("  [%s] %d hoteles con habitación privada" % (zona, len(hoteles)))
            for h in hoteles:
                vistos += 1
                pp = h["total"] / ADULTOS
                anterior = historico.get(h["nombre"])
                if anterior is None:
                    historico[h["nombre"]] = {"precio": h["total"], "minimo": h["total"],
                                              "maximo": h["total"], "zona": zona,
                                              "url": h["url"], "visto": time.strftime("%Y-%m-%d %H:%M")}
                    avisos.append("🆕 <b>Hotel nuevo</b> en %s\n<b>%s</b>\n%.2f € las 6 noches (%.2f €/persona)%s"
                                  % (zona, h["nombre"], h["total"], pp,
                                     ("\n👉 <a href=\"%s\">Ver en Booking</a>" % h["url"]) if h["url"] else ""))
                    continue
                precio_viejo = anterior["precio"]
                anterior["maximo"] = max(anterior.get("maximo", precio_viejo), h["total"])
                if h["total"] < precio_viejo - UMBRAL:
                    anterior["minimo"] = min(anterior.get("minimo", precio_viejo), h["total"])
                    avisos.append("📉 <b>Bajada en %s</b>\n<b>%s</b>\nAntes %.2f € → ahora <b>%.2f €</b> "
                                  "(%.2f €/persona)\nMínimo visto: %.2f €%s"
                                  % (zona, h["nombre"], precio_viejo, h["total"], pp, anterior["minimo"],
                                     ("\n👉 <a href=\"%s\">Ver en Booking</a>" % h["url"]) if h["url"] else ""))
                anterior["precio"] = h["total"]
                anterior["visto"] = time.strftime("%Y-%m-%d %H:%M")
                anterior["url"] = h["url"] or anterior.get("url")
            time.sleep(2)
        b.close()

    with open(HISTORICO, "w", encoding="utf-8") as fh:
        json.dump(historico, fh, ensure_ascii=False, indent=1)

    if not avisos:
        print("  sin novedades (%d hoteles vistos)" % vistos)
    elif not destino:
        print("  %d avisos generados pero TELEGRAM_CHAT_ID no está configurado" % len(avisos))
    else:
        texto = "\n\n".join(avisos[:8])
        if len(avisos) > 8:
            texto += "\n\n... y %d más." % (len(avisos) - 8)
        ok = notifier.telegram(destino, texto)
        print("  %d avisos (%d hoteles vistos) -> enviado: %s" % (len(avisos), vistos, ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
