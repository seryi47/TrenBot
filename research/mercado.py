#!/usr/bin/env python3
"""¿Alguien vende más barato que la propia aerolínea?

El bot pregunta a Ryanair y a Wizz cuánto cuestan SUS billetes. Eso no es el
precio de mercado: revendedores como Kiwi o Trip.com suelen estar por debajo
del precio oficial. Esto contrasta con Google Flights, que sí los agrega.

Skyscanner y Kiwi no se dejan (captcha y clave de API); Google Flights sí.
"""
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

RAIZ = os.path.dirname(os.path.abspath(__file__))


def consultar(pg, o, d, ida, vuelta, adultos=2):
    q = ("https://www.google.com/travel/flights?hl=es&curr=EUR&q="
         "Flights%%20to%%20%s%%20from%%20%s%%20on%%20%s%%20through%%20%s"
         "%%20nonstop%%20for%%20%d%%20adults" % (d, o, ida, vuelta, adultos))
    pg.goto(q, timeout=90000, wait_until="domcontentloaded")
    pg.wait_for_timeout(5000)
    for sel in ("button:has-text('Aceptar todo')", "button:has-text('Rechazar todo')"):
        try:
            if pg.locator(sel).first.is_visible(timeout=2000):
                pg.locator(sel).first.click()
                pg.wait_for_timeout(5000)
                break
        except Exception:
            pass
    pg.wait_for_timeout(14000)
    t = pg.inner_text("body")
    if "robot" in t.lower() or "unusual traffic" in t.lower():
        return None, "bloqueado"
    # Google muestra el total del viaje para todos los pasajeros.
    precios = sorted({int(x.replace(".", ""))
                      for x in re.findall(r"(\d{2,4}(?:\.\d{3})?)\s*€", t)})
    precios = [p for p in precios if p >= 40]
    if not precios:
        return None, "sin precios"
    return precios[0], ("%d pasajeros" % adultos)


def main():
    rutas = json.load(open(os.path.join(RAIZ, "mercado_rutas.json"), encoding="utf-8"))
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(locale="es-ES", timezone_id="Europe/Madrid",
                            viewport={"width": 1500, "height": 1100},
                            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/140.0.0.0 Safari/537.36"))
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        pg = ctx.new_page()
        for r in rutas:
            precio, nota = consultar(pg, r["o"], r["d"], r["ida"], r["vuelta"])
            out["%s-%s" % (r["o"], r["d"])] = {"mercado": precio, "nota": nota,
                                               "nuestro_total": r.get("nuestro")}
            ref = r.get("nuestro")
            print("  %s→%s  mercado %-8s  nosotros %-8s  %s"
                  % (r["o"], r["d"], precio if precio else "-", ref if ref else "-",
                     ("Δ %+d €" % (precio - ref)) if precio and ref else nota))
            sys.stdout.flush()
        b.close()
    json.dump(out, open(os.path.join(RAIZ, "mercado.json"), "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
