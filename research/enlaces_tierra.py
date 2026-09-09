"""Conexiones por tierra realistas entre aeropuertos (tren/bus directo).

horas = duracion tipica puerta a puerta del trayecto entre ciudades.
Solo se incluyen saltos que se hacen comodamente en un viaje de 3-4 dias.
"""

ENLACES = {
    # Centroeuropa: el nucleo del viaje
    ("BTS", "VIE"): (1.2, "bus RegioJet/Slovak Lines, ~1h15, 8-12 EUR"),
    ("BTS", "BUD"): (2.7, "tren directo RegioJet/MAV, ~2h40, 15-20 EUR"),
    ("VIE", "BUD"): (2.7, "tren Railjet directo, ~2h40, 20-30 EUR"),
    ("VIE", "PRG"): (4.0, "tren Railjet directo, ~4h, 20-35 EUR"),
    ("BTS", "PRG"): (4.0, "tren/bus RegioJet directo, ~4h, 15-25 EUR"),
    ("VIE", "LNZ"): (1.3, "tren Railjet, ~1h20, 15-25 EUR"),
    ("VIE", "SZG"): (2.5, "tren Railjet, ~2h30, 20-40 EUR"),
    ("BTS", "LNZ"): (2.5, "tren via Viena, ~2h30"),
    ("PRG", "PED"): (1.0, "tren directo, ~1h, 5-10 EUR"),
    ("VIE", "PED"): (5.0, "tren via Praga o Brno, ~5h"),
    ("BTS", "PED"): (5.0, "tren via Brno, ~5h"),
    ("BUD", "PED"): (7.5, "demasiado lejos"),
    # Polonia y alrededores
    ("KRK", "KTW"): (1.3, "tren directo, ~1h20, 5-8 EUR"),
    ("KRK", "WAW"): (2.4, "tren PKP IC, ~2h20, 15-25 EUR"),
    ("KTW", "WAW"): (2.6, "tren PKP IC, ~2h30, 15-25 EUR"),
    ("KTW", "PRG"): (5.0, "bus directo, ~5h, 20-30 EUR"),
    ("KTW", "PED"): (5.5, "tren via Praga, ~5h30"),
    ("LNZ", "PED"): (5.5, "bus a Praga + tren, ~5h30"),
    ("LNZ", "PRG"): (4.5, "bus RegioJet directo, ~4h30"),
    ("KRK", "BTS"): (6.0, "demasiado lejos"),
    ("SZG", "BTS"): (4.5, "tren via Viena, ~4h30"),
    ("ZAG", "VCE"): (5.0, "bus directo Zagreb-Venecia, ~5h"),
    ("ZAG", "TSF"): (5.0, "bus directo Zagreb-Venecia, ~5h"),
    ("KRK", "PRG"): (6.5, "demasiado lejos"),
    ("WAW", "WMI"): (0.8, "mismo Varsovia"),
    ("KTW", "BTS"): (4.5, "bus directo FlixBus/RegioJet, ~4h30, 15-25 EUR"),
    # Balcanes y Adriatico
    ("ZAG", "LJU"): (2.3, "tren/bus directo, ~2h15, 10-15 EUR"),
    ("ZAG", "BUD"): (5.5, "tren directo, ~5h30, 25-35 EUR"),
    ("ZAG", "VIE"): (6.0, "tren directo, ~6h"),
    ("ZAG", "BEG"): (5.5, "bus directo, ~5h30"),
    # Alemania / Chequia
    ("BER", "PRG"): (4.3, "tren EC directo, ~4h15, 20-30 EUR"),
    ("BER", "PED"): (5.3, "tren via Praga, ~5h20"),
    ("NUE", "PRG"): (3.5, "bus Flixbus directo, ~3h30, 15-25 EUR"),
    ("FMM", "SZG"): (2.5, "tren via Munich, ~2h30"),
    ("NUE", "VIE"): (5.0, "tren, ~5h"),
    # Italia norte
    ("VCE", "TSF"): (0.6, "misma Venecia"),
    ("MXP", "BGY"): (1.2, "ambos en Milan"),
    ("TSF", "LJU"): (3.5, "bus directo, ~3h30"),
    ("VCE", "LJU"): (3.5, "bus directo, ~3h30"),
}

# Se rellena en ambos sentidos.
for (a, b), v in list(ENLACES.items()):
    ENLACES[(b, a)] = v


def enlace(a, b):
    """Devuelve (horas, descripcion) o None si no hay salto por tierra razonable."""
    if a == b:
        return (0.0, "mismo aeropuerto")
    return ENLACES.get((a, b))
