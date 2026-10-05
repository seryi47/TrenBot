"""Brussels Airlines (SN): hasta dónde se llega sin clave y sin scraping.

Qué se consiguió
----------------
El buscador de la home (www.brusselsairlines.com) habla con una API REST propia
colgada de /service/api. La tabla completa de rutas (unas 120) está dentro de
los .js que descarga la home; se cosechan con Playwright igual que con Vueling.
El endpoint que cierra la búsqueda es:

    POST https://www.brusselsairlines.com/service/api/booking/flightAvailability

No pide token ni clave: basta con las cabeceras de "portal" (x-portal: SN,
x-portal-site, x-portal-language). Devuelve el RELEVO al motor de reservas, no
los precios:

    {"targetURL":"https://shop.brusselsairlines.com/booking/availability?lang=es-ES&portalCountry=ES",
     "methodGet":false,
     "parameters":[{"key":"search","values":["{...}"]}]}

Dónde se para
-------------
shop.brusselsairlines.com (el motor de reservas, común a todo el grupo
Lufthansa: shop.lufthansa.com, shop.swiss.com, shop-uat...) está detrás de un
Cloudflare Turnstile con pre-clearance (https://shop.brusselsairlines.com/preclearance,
sitekey 0x4AAAAAACVC4msa05_fUfuX, widget invisible en un iframe de la home).

Cualquier petición al shop sin ese pre-clearance responde:

    403  cf-mitigated: challenge   server: cloudflare

Probado y fallido: curl_cffi con impersonate chrome / chrome131 / chrome124 /
safari17_0 / edge101 (los cinco, 403 con cf-mitigated: challenge; aquí NO es
cuestión de huella TLS como en Transavia) y navegador real controlado por CDP
(Turnstile no lo da por bueno y el reto no se resuelve nunca).

Es decir: el precio de SN sigue teniendo que venir de Google Flights
(providers/mercado.py). Esto de aquí sirve para rehacer el camino si algún día
cae esa protección.
"""

import json

from curl_cffi import requests as cr

BASE = "https://www.brusselsairlines.com/service/api"
CABECERAS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES;q=1",
    "Content-Type": "application/json",
    "Referer": "https://www.brusselsairlines.com/es/es/homepage",
    # Sin estas tres responde 400 {"error":"Tenant [null] not found"}
    "x-portal": "SN",
    "x-portal-site": "ES",
    "x-portal-language": "es",
}


def sesion():
    s = cr.Session(impersonate="chrome")
    s.headers.update(CABECERAS)
    return s


def valida_ruta(s, origen, destino, fecha):
    """Cabinas disponibles en esa ruta. 200 = la ruta existe para SN."""
    r = s.post(BASE + "/ondcontrol/validateOriginAndDestination",
               json={"flightSegments": [{"originCode": origen,
                                         "destinationCode": destino,
                                         "travelDatetime": fecha + "T00:00:00"}]},
               timeout=40)
    return r.status_code, (r.json() if r.status_code == 200 else r.text[:200])


def relevo(s, origen, destino, fecha, adultos=1):
    """Devuelve (url_del_shop, cuerpo_del_formulario). maxStops 0 = solo directos."""
    consulta = {
        "tripType": "O", "cabin": "E",
        "adults": adultos, "children": 0, "infants": 0,
        "maxStops": 0,              # el buscador manda esto cuando marcas "Nonstop only"
        "travelOption": "PRIVATE", "farePreference": "DEFAULT",
        "flightSegments": [{"originCode": origen, "destinationCode": destino,
                            "travelDatetime": fecha + "T00:00:00"}],
    }
    r = s.post(BASE + "/booking/flightAvailability", json=consulta, timeout=60)
    if r.status_code != 200:
        return None, r.text[:300]
    j = r.json()
    return j.get("targetURL"), j["parameters"][0]["values"][0]


def intenta_shop(url, cuerpo):
    """Siempre 403 hoy. Se deja para comprobar si algún día abren la mano."""
    s = cr.Session(impersonate="chrome")
    r = s.post(url, data={"search": cuerpo}, timeout=60)
    return r.status_code, r.headers.get("cf-mitigated"), len(r.text)


if __name__ == "__main__":
    s = sesion()
    for o, d, f in [("ALC", "BRU", "2026-12-04"),
                    ("ALC", "BRU", "2026-12-05"),
                    ("BRU", "ALC", "2026-12-08")]:
        print(o, d, f, valida_ruta(s, o, d, f))
        url, cuerpo = relevo(s, o, d, f)
        print("   ->", url)
        print("   ->", cuerpo)
        print("   shop:", intenta_shop(url, cuerpo))
