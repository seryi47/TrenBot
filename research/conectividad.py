"""¿Se puede ir por tierra de un aeropuerto a otro en un fin de semana?

La versión anterior usaba una lista escrita a mano de Centroeuropa, y por eso se
dejó fuera combinaciones perfectamente válidas (París + Bruselas, Colonia +
Bruselas...). Aquí se decide con dos criterios objetivos:

  1. que los dos aeropuertos estén en la misma masa de tierra, y
  2. que la distancia por carretera estimada dé un trayecto de 5 h o menos.

Las islas quedan aisladas (no hay tren que valga). Gran Bretaña sí cuenta como
conectada al continente, pero solo por el Eurotúnel, y eso se marca aparte
porque el Eurostar cuesta bastante más que un tren normal.
"""

import math

# Islas sin conexión por tierra con nada (ferry o avión, no valen aquí).
ISLAS = {
    "PMI": "baleares", "IBZ": "baleares", "MAH": "baleares",
    "ACE": "canarias", "LPA": "canarias", "TFS": "canarias", "TFN": "canarias",
    "FUE": "canarias", "SPC": "canarias",
    "CTA": "sicilia", "PMO": "sicilia", "TPS": "sicilia", "LMP": "lampedusa",
    "CAG": "cerdena", "AHO": "cerdena", "OLB": "cerdena",
    "MLA": "malta", "LCA": "chipre", "PFO": "chipre", "KEF": "islandia",
    "CFU": "corfu", "RHO": "rodas", "HER": "creta", "CHQ": "creta",
    "JMK": "miconos", "JTR": "santorini", "JSI": "skiathos",
    "EFL": "cefalonia", "ZTH": "zante", "KGS": "kos", "SMI": "samos",
}
# Irlanda del Norte está en la isla de Irlanda, no en Gran Bretaña.
IRLANDA_NORTE = {"BFS", "BHD", "LDY"}

CONTINENTAL = {
    "es", "pt", "fr", "be", "nl", "lu", "de", "ch", "at", "it", "cz", "sk",
    "pl", "hu", "si", "hr", "ba", "rs", "me", "mk", "al", "gr", "bg", "ro",
    "md", "dk", "se", "no", "fi", "lt", "lv", "ee", "ua", "xk",
}


def masa(iata, cc):
    """Devuelve la masa de tierra del aeropuerto."""
    cc = (cc or "").lower()
    if iata in ISLAS:
        return ISLAS[iata]
    if iata in IRLANDA_NORTE or cc == "ie":
        return "irlanda"
    if cc == "gb":
        return "granbretana"
    if cc in CONTINENTAL:
        return "continente"
    return "otra_" + cc


def km(a, b):
    """Distancia en línea recta entre dos (lat, lon)."""
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


# Duraciones REALES comprobadas con horarios (FlixBus, operadoras ferroviarias).
# La estimación por distancia se queda corta donde hay montañas o el trazado da
# un rodeo, y proponía viajes imposibles como Marsella-Turín en 4,8 h.
REALES = {
    ("MRS", "TRN"): (6.2, "autobús con cambio, ~6h10 cruzando los Alpes"),
    ("BTS", "ZAG"): (6.1, "autobús con cambio, ~6h05"),
    ("BTS", "KRK"): (6.7, "autobús con cambio, ~6h40"),
    ("BGY", "FMM"): (8.7, "~8h40 cruzando los Alpes"),
    ("MXP", "FMM"): (8.1, "~8h05 cruzando los Alpes"),
    ("HHN", "CRL"): (6.1, "autobús con cambio, ~6h05"),
    ("VIE", "ZAG"): (4.8, "autobús directo, ~4h50"),
    ("BTS", "PRG"): (4.1, "autobús directo RegioJet, ~4h05"),
    ("VIE", "PRG"): (3.9, "tren o autobús directo, ~3h55"),
    ("BTS", "VIE"): (0.9, "autobús directo, ~52 min"),
    ("BTS", "BUD"): (2.3, "tren directo, ~2h20"),
    ("CGN", "CRL"): (3.7, "tren ICE 1h50 hasta Bruselas, o autobús 3h40"),
    ("BVA", "CRL"): (3.6, "autobús París-Bruselas 3h35, más los traslados"),
    ("NRN", "CRL"): (2.7, "autobús directo, ~2h40"),
    ("LNZ", "PRG"): (3.8, "autobús directo, ~3h45"),
    ("KTW", "PRG"): (5.3, "autobús directo, ~5h15"),
    ("WRO", "PED"): (2.9, "tren directo Baltic Express, ~2h50"),
    ("BFS", "DUB"): (2.2, "tren Enterprise, ~2h10"),
    # Irlanda: sin autopista transversal ni bus directo, todo va por Dublín
    ("NOC", "BFS"): (5.9, "bus con transbordos, ~5h56"),
    ("SNN", "BFS"): (6.9, "bus con transbordos, ~6h53"),
    ("NOC", "DUB"): (4.0, "bus directo, ~4h"),
    ("SNN", "DUB"): (3.5, "bus directo, ~3h30"),
    # Hahn está en mitad del campo: sumar ~1h45 hasta Fráncfort
    ("EIN", "HHN"): (7.0, "bus a Fráncfort 5h35 + 1h45 hasta Hahn"),
    ("CRL", "EIN"): (3.0, "bus/tren, ~3h"),
    ("EIN", "CGN"): (2.5, "bus directo, ~2h30"),
}
for (x, y), v in list(REALES.items()):
    REALES[(y, x)] = v


def enlace(a, b, tope_horas=5.0):
    """(horas, descripción) si se puede ir por tierra; None si no.

    Se estima el trayecto real como 1,25 veces la línea recta (los trenes y
    autobuses no van rectos) a 80 km/h de media, más media hora de trámites.
    """
    if a["iata"] == b["iata"]:
        return 0.0, "mismo aeropuerto", 0
    conocido = REALES.get((a["iata"], b["iata"]))
    if conocido:
        horas, texto = conocido
        return None if horas > tope_horas else (horas, texto, 0)
    ma, mb = masa(a["iata"], a.get("cc")), masa(b["iata"], b.get("cc"))
    eurotunel = {ma, mb} == {"granbretana", "continente"}
    if ma != mb and not eurotunel:
        return None
    d = km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
    carretera = d * 1.25
    horas = carretera / 80.0 + 0.5
    if horas > tope_horas:
        return None
    if eurotunel:
        # El Eurostar tarda 2 h a Bruselas y 2h20 a París, mucho menos de lo que
        # sale por distancia, así que aquí no vale la estimación por carretera.
        # Solo tiene sentido saliendo de Londres, y sumando el trayecto hasta
        # St Pancras desde Stansted/Luton/Gatwick.
        LONDRES = {"LON", "STN", "LGW", "LTN", "LHR", "LCY", "SEN"}
        if not (LONDRES & {a["iata"], b["iata"]}) or d > 500:
            return None
        return 4.0, "Eurostar por el Eurotúnel (60-140 € por trayecto, caro)", round(d)
    return horas, "tren o autobús (~%d km)" % round(carretera), round(d)
