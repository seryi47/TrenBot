#!/usr/bin/env python3
"""Prueba la lógica de avisos sin tocar la vigilancia real ni enviar spam.

Trabaja sobre una COPIA de watches.json y con un notificador que captura los
mensajes en vez de mandarlos. Comprueba los dos disparadores:
  1. bajada de precio (precio actual < último visto - umbral)
  2. objetivo alcanzado (precio actual <= max_price)
Con --telegram manda además UN aviso real, para verificar el canal de punta a punta.
"""

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botviajes.engine import Engine           # noqa: E402
from botviajes.notifier import Notifier       # noqa: E402
from botviajes.util_env import load_env       # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))


class Capturador(Notifier):
    """Notificador de mentira: apunta los mensajes en vez de enviarlos."""

    def __init__(self):
        super().__init__(mac_alerts=False, open_browser=False)
        self.mensajes = []

    def telegram(self, chat_id, text):
        self.mensajes.append(text)
        return True

    def mac(self, *a, **k):
        pass

    def browser(self, *a, **k):
        pass


def motor_de_prueba(watches):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(watches, tmp, ensure_ascii=False)
    tmp.close()
    cap = Capturador()
    return Engine(cap, default_chat_id="0", state_file=tmp.name), cap, tmp.name


def main():
    load_env()
    reales = json.load(open(os.path.join(RAIZ, "watches.json"), encoding="utf-8"))
    base = [w for w in reales if w.get("enabled", True) and w["providers"] == ["ryanair"]][0]

    # El precio se consulta AHORA, no se coge el guardado: entre una cosa y otra
    # la aerolínea puede haberlo cambiado y el test fallaría sin haber ningún
    # fallo real (ya pasó una vez).
    from botviajes.providers import get_provider
    ofertas = [o for o in get_provider("ryanair").search(
        base["origin"], base["destination"], base["date"],
        adults=base.get("adults", 1)) if o.departure == base.get("time")]
    if not ofertas:
        print("No hay oferta para %s ahora mismo; no se puede probar." % base["name"])
        return 1
    precio_real = ofertas[0].price
    print("Ruta de prueba: %s  (precio real ahora: %.2f €)\n" % (base["name"], precio_real))

    fallos = []

    # --- 1. BAJADA: se finge que la última vez costaba 40 € más -------------
    w = copy.deepcopy(base)
    w["ultimo_precio"] = precio_real + 40
    w["max_price"] = 1          # imposible: así no se mezcla con el otro aviso
    motor, cap, tmp = motor_de_prueba([w])
    _, _, aviso = motor.revisar(motor.watches[0])
    # Se comprueba el contenido, no una frase literal: la cabecera cambió una
    # vez ("BAJA DE PRECIO" -> mínimo histórico / ha bajado) y el test se quedó
    # comprobando un texto que ya no existía, dando un fallo que no era real.
    CABECERAS = ("PRECIO MÍNIMO", "Ha bajado")
    ok = (aviso is not None
          and any(c in aviso for c in CABECERAS)
          and "%.2f" % precio_real in aviso                  # el precio de ahora
          and "Sale de" in aviso and "Llega a" in aviso)      # y las horas
    print("1) Aviso de BAJADA .............. %s" % ("OK" if ok else "FALLA"))
    if not ok and aviso:
        print("   (llegó un aviso pero no cuadra con lo esperado)")
    if ok:
        print("   " + aviso.replace("\n", "\n   ")[:420])
        bajada_texto = aviso
    else:
        fallos.append("no se disparó el aviso de bajada"); bajada_texto = None
    os.unlink(tmp)

    # --- 2. SUBIDA: no debe avisar ------------------------------------------
    w = copy.deepcopy(base)
    w["ultimo_precio"] = precio_real - 40      # antes era más barato
    w["max_price"] = 1
    motor, cap, tmp = motor_de_prueba([w])
    _, _, aviso = motor.revisar(motor.watches[0])
    ok2 = aviso is None
    print("\n2) Si SUBE, no avisa ............ %s" % ("OK" if ok2 else "FALLA"))
    if not ok2:
        fallos.append("avisó de una subida como si fuera bajada")
    os.unlink(tmp)

    # --- 3. OBJETIVO alcanzado ----------------------------------------------
    w = copy.deepcopy(base)
    w["max_price"] = precio_real + 10                    # el precio ya lo cumple
    w.pop("ultimo_precio", None)
    motor, cap, tmp = motor_de_prueba([w])
    n = motor.check_once()
    ok3 = (n == 1 and cap.mensajes and "DISPONIBLES" in cap.mensajes[0]
           and "Sale de" in cap.mensajes[0])
    print("\n3) Aviso de OBJETIVO ............ %s" % ("OK" if ok3 else "FALLA"))
    if ok3:
        print("   " + cap.mensajes[0].replace("\n", "\n   ")[:380])
    else:
        fallos.append("no se disparó el aviso de objetivo")
    os.unlink(tmp)

    # --- 4. El enlace de compra del aviso es el bueno ------------------------
    ok4 = bool(cap.mensajes) and "ryanair.com" in cap.mensajes[0] and "originIata" in cap.mensajes[0]
    print("\n4) Lleva enlace de compra ....... %s" % ("OK" if ok4 else "FALLA"))
    if not ok4:
        fallos.append("el aviso no lleva enlace de compra válido")

    # --- 5. Un precio de 0 nunca debe aceptarse -----------------------------
    from botviajes.models import Offer
    cero = Offer(provider="wizz", origin="A", destination="B", date="2026-10-09",
                 departure="09:35", label="W6", price=0.0, available=True)
    normal = Offer(provider="wizz", origin="A", destination="B", date="2026-10-09",
                   departure="09:35", label="W6", price=80.0, available=True)
    ok5 = (Engine._mas_barata([cero]) is None
           and Engine._mas_barata([cero, normal]) is normal)
    print("\n5) Un 0,00 € nunca cuela ........ %s" % ("OK" if ok5 else "FALLA"))
    if not ok5:
        fallos.append("un precio de 0 se colaba como válido")

    # --- 6. Canal real de Telegram ------------------------------------------
    if "--telegram" in sys.argv and bajada_texto:
        real = Notifier(mac_alerts=False, open_browser=False)
        enviado = real.telegram(os.environ.get("TELEGRAM_CHAT_ID", ""),
                                "🧪 <b>PRUEBA</b> — no es un aviso real, "
                                "estoy comprobando que el canal funciona.\n\n" + bajada_texto)
        print("\n6) Envío real a Telegram ........ %s" % ("OK" if enviado else "FALLA"))
        if not enviado:
            fallos.append("no se pudo enviar a Telegram")

    print("\n" + ("TODO CORRECTO" if not fallos else "PROBLEMAS: " + "; ".join(fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
