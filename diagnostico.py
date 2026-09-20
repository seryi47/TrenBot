#!/usr/bin/env python3
"""Comprueba si a la aerolínea le estamos pareciendo un bot.

Se ejecuta a mano, tanto en el Mac como en GitHub Actions, para comparar las
MISMAS consultas desde dos IPs distintas. Si los precios coinciden, no hay ni
caché ni trato distinto según quién pregunte; si no, sí lo hay.
"""
import json
import sys

import curl_cffi.requests as cr

from botviajes.providers import get_provider

RUTAS = [("wizz", "OTP", "ALC", "2026-10-11"),
         ("wizz", "KTW", "ALC", "2026-10-11"),
         ("ryanair", "PED", "ALC", "2026-10-11"),
         ("ryanair", "LNZ", "ALC", "2026-10-12"),
         ("wizz", "ALC", "GDN", "2026-10-08"),
         ("wizz", "GDN", "ALC", "2026-10-11"),
         ("wizz", "ALC", "BTS", "2026-10-09")]


def main():
    try:
        ip = cr.get("https://api.ipify.org", timeout=20).text.strip()
    except Exception:
        ip = "?"
    print("IP desde la que pregunto: %s" % ip)
    print("%-22s %10s %-12s %s" % ("ruta", "precio", "tipo", "hora"))
    print("-" * 62)
    salida = {}
    for prov, o, d, f in RUTAS:
        try:
            offs = get_provider(prov).search(o, d, f, adults=2)
            buenas = [x for x in offs if x.price and x.price > 0]
            if buenas:
                mejor = min(buenas, key=lambda x: x.price)
                tipo = "sin venta" if (mejor.raw or {}).get("sin_venta") else "firme"
                print("%-22s %10.2f %-12s %s" % ("%s %s→%s" % (prov, o, d),
                                                 mejor.price, tipo, mejor.departure))
                salida["%s|%s|%s" % (prov, o, d)] = [mejor.price, tipo, mejor.departure]
            else:
                print("%-22s %10s %-12s" % ("%s %s→%s" % (prov, o, d), "-", "sin precio"))
                salida["%s|%s|%s" % (prov, o, d)] = None
        except Exception as e:
            print("%-22s  ERROR %s" % ("%s %s→%s" % (prov, o, d), str(e)[:60]))
            salida["%s|%s|%s" % (prov, o, d)] = "error"
    print("\nJSON:%s" % json.dumps({"ip": ip, "r": salida}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
