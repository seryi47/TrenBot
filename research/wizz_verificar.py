"""Reconsulta Wizz para 2 adultos (el precio por persona puede subir si la
tarifa barata solo tiene 1 asiento). Va despacio para no comerse un 429."""
import json, time
from curl_cffi import requests as cr

BASE = "https://be.wizzair.com/29.14.0/Api"
RUTAS = [("ALC", "BTS"), ("ALC", "BUD"), ("ALC", "KTW"), ("ALC", "WAW"),
         ("ALC", "GDN"), ("ALC", "VCE"), ("ALC", "MXP")]


def ses():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Origin": "https://www.wizzair.com",
                      "Referer": "https://www.wizzair.com/es-es",
                      "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "es-ES,es;q=0.9",
                      "Content-Type": "application/json"})
    s.post(BASE + "/asset/culture", json={"languageCode": "es-es"}, timeout=30)
    s.headers["X-RequestVerificationToken"] = s.cookies.get("RequestVerificationToken")
    return s


def pedir(s, o, d, adultos):
    # ALC siempre primero: asi Wizz devuelve los importes en EUR.
    pl = {"flightList": [{"departureStation": o, "arrivalStation": d,
                          "from": "2026-10-06", "to": "2026-10-16"},
                         {"departureStation": d, "arrivalStation": o,
                          "from": "2026-10-06", "to": "2026-10-16"}],
          "priceType": "regular", "adultCount": adultos,
          "childCount": 0, "infantCount": 0}
    for i in range(5):
        r = s.post(BASE + "/search/timetable", json=pl, timeout=60)
        if r.status_code == 200:
            return r.json()
        time.sleep(20 * (i + 1))
    return None


def main():
    s = ses()
    res = {}
    for o, d in RUTAS:
        fila = {}
        for adultos in (1, 2):
            j = pedir(s, o, d, adultos)
            if j is None:
                print("%s<->%s adultos=%d : BLOQUEADO" % (o, d, adultos)); continue
            for clave in ("outboundFlights", "returnFlights"):
                for f in j.get(clave, []) or []:
                    dia = f["departureDate"][:10]
                    if dia not in ("2026-10-08", "2026-10-09", "2026-10-11", "2026-10-12"):
                        continue
                    fila.setdefault((f["departureStation"], f["arrivalStation"], dia), {})[adultos] = (
                        f["price"]["amount"], f["price"]["currencyCode"],
                        [x[11:16] for x in f["departureDates"]])
            time.sleep(12)
        for k, v in sorted(fila.items()):
            p1 = v.get(1); p2 = v.get(2)
            print("%s->%s %s | 1 adulto: %s | 2 adultos: %s | sale %s" % (
                k[0], k[1], k[2][5:],
                ("%.2f %s" % (p1[0], p1[1])) if p1 else "-",
                ("%.2f %s" % (p2[0], p2[1])) if p2 else "-",
                ",".join((p2 or p1)[2]) if (p1 or p2) else "-"))
        res["%s-%s" % (o, d)] = {str(k): v for k, v in fila.items()}
    json.dump(res, open("research/wizz_2adultos.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
