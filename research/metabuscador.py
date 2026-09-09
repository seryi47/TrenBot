"""Contraste con Google Flights: comprueba que no hay otra aerolinea mas barata."""
import asyncio, json, os, re, sys
from playwright.async_api import async_playwright

RUTAS = [("ALC", "VIE", "2026-10-08"), ("VIE", "ALC", "2026-10-11"),
         ("VIE", "ALC", "2026-10-12"), ("ALC", "BTS", "2026-10-09"),
         ("BTS", "ALC", "2026-10-11"), ("BTS", "ALC", "2026-10-12"),
         ("ALC", "BUD", "2026-10-09"), ("BUD", "ALC", "2026-10-11"),
         ("BUD", "ALC", "2026-10-12"), ("ALC", "PRG", "2026-10-09"),
         ("PRG", "ALC", "2026-10-11"), ("PRG", "ALC", "2026-10-12")]


async def main():
    salida = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True,
                                    args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(locale="es-ES", timezone_id="Europe/Madrid",
            viewport={"width": 1500, "height": 1100},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"))
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        pg = await ctx.new_page()
        for o, d, fecha in RUTAS:
            url = ("https://www.google.com/travel/flights?q=vuelos%%20de%%20%s%%20a%%20%s"
                   "%%20el%%20%s%%20solo%%20ida&curr=EUR&hl=es&gl=ES" % (o, d, fecha))
            try:
                await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(o, d, fecha, "goto err", e); continue
            for sel in ["button:has-text('Aceptar todo')", "button:has-text('Rechazar todo')",
                        "form button", "button[aria-label*='Aceptar']"]:
                try:
                    await pg.click(sel, timeout=3000); break
                except Exception:
                    pass
            await pg.wait_for_timeout(9000)
            filas = []
            try:
                els = await pg.query_selector_all("li")
                for e in els[:40]:
                    t = (await e.inner_text()).replace("\n", " | ")
                    if re.search(r"\d{1,2}:\d{2}", t) and "€" in t:
                        filas.append(re.sub(r"\s+", " ", t)[:260])
            except Exception as e:
                print("parse err", e)
            salida["%s-%s-%s" % (o, d, fecha)] = filas
            print("\n### %s->%s %s  (%d resultados)" % (o, d, fecha[5:], len(filas)))
            for f in filas[:6]:
                print("   ", f[:230])
        await b.close()
    json.dump(salida, open("research/metabuscador.json", "w"), ensure_ascii=False, indent=1)

asyncio.run(main())
