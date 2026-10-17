#!/usr/bin/env python3
"""Averigua tu userId de LINE sin montar ningún webhook ni túnel (ngrok).

LINE expone un endpoint que lista los userId de quien ha añadido la cuenta
oficial como amiga. Como solo tú (o quien vaya a recibir los avisos) la
habrás añadido, esta lista trae justo lo que hace falta para LINE_USER_ID.

Uso:
  1. Crea el canal "Messaging API" en developers.line.biz y copia el
     "Channel access token" (pestaña Messaging API del canal).
  2. Escanea el QR de esa misma pestaña para añadir la cuenta como amigo.
  3. ./venv/bin/python line_userid.py <CHANNEL_ACCESS_TOKEN>
"""
import sys

import requests


def main():
    if len(sys.argv) != 2:
        print("Uso: python line_userid.py <CHANNEL_ACCESS_TOKEN>")
        return 1
    token = sys.argv[1]
    r = requests.get(
        "https://api.line.me/v2/bot/followers/ids",
        headers={"Authorization": "Bearer " + token},
        timeout=20,
    )
    if not r.ok:
        print("Error %s: %s" % (r.status_code, r.text[:300]))
        print("\nSi da 403/404, el plan del canal no tiene este endpoint "
              "habilitado todavía (a veces tarda unos minutos tras crear el "
              "canal). Vuelve a intentarlo en un rato.")
        return 1
    ids = r.json().get("userIds") or []
    if not ids:
        print("Todavía no hay nadie en la lista. Asegúrate de haber añadido "
              "la cuenta como amigo (escanea el QR de la pestaña Messaging "
              "API) y vuelve a lanzar este script.")
        return 1
    print("userId encontrado(s):")
    for uid in ids:
        print(" ", uid)
    if len(ids) == 1:
        print("\nEse es tu LINE_USER_ID.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
