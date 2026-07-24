"""Proveedor Iryo (ILSA) — EXPERIMENTAL / no implementado todavía.

Iryo no expone una API pública documentada como Renfe u Ouigo; su web usa el
motor de reservas de su proveedor (tipo Trenitalia/Sqills). Para implementarlo
hay que capturar con las DevTools del navegador la llamada real de búsqueda
(pestaña Network) en https://iryo.eu y replicar aquí el endpoint + payload.

Mientras tanto este proveedor no devuelve resultados (no rompe el resto).
Pasos para completarlo están en el README (sección "Añadir un proveedor").
"""

from typing import List

from botviajes.models import Offer
from botviajes.providers.base import Provider


class IryoProvider(Provider):
    name = "iryo"

    def search(self, origin, destination, date) -> List[Offer]:
        # TODO: implementar contra el backend real de iryo.eu.
        raise NotImplementedError(
            "Iryo aún no está implementado. Ver README → 'Añadir un proveedor'."
        )
