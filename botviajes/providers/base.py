"""Interfaz común de proveedores y utilidades de resolución de estaciones."""

import json
import os
import unicodedata
from typing import List, Optional

from botviajes.models import Offer

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def _norm(text) -> str:
    """Normaliza para comparar: minúsculas, sin acentos, sin signos raros."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()


class Provider:
    """Clase base. Cada proveedor implementa `search`."""

    name = "base"

    def search(self, origin: str, destination: str, date: str,
               adults: int = 1) -> List[Offer]:
        """Busca ofertas. `date` en formato YYYY-MM-DD. Devuelve lista de Offer.

        `adults` solo lo usan los proveedores de vuelo: en las aerolineas de bajo
        coste el precio por persona sube si la tarifa barata ya no tiene asientos
        para todo el grupo, asi que buscar para 1 y viajar 2 da un precio irreal.
        """
        raise NotImplementedError

    # Utilidades comunes -----------------------------------------------------
    @staticmethod
    def load_json(filename: str):
        path = os.path.join(DATA_DIR, filename)
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def match_station(query: str, candidates: dict, name_getter, code_getter,
                      synonyms_getter=None):
        """Resuelve un nombre de estación a (nombre_canonico, codigo).

        candidates: iterable de items; name_getter(item)->str, code_getter(item)->str.
        Estrategia: coincidencia exacta normalizada > subcadena > sinónimos.
        Devuelve (None, None) si no encuentra nada.
        """
        q = _norm(query)
        exact, partial, partial_len = None, None, None
        for item in candidates:
            name = name_getter(item)
            nn = _norm(name)
            if nn == q:
                return name, code_getter(item)
            # Entre varias coincidencias parciales ambiguas, la mejor es la
            # más corta (la más cercana a la query): antes se quedaba con la
            # PRIMERA que apareciera en el JSON, que depende del orden del
            # fichero y podía resolver a la estación equivocada.
            if (q in nn or nn in q) and len(q) >= 3:
                if partial_len is None or len(nn) < partial_len:
                    partial = (name, code_getter(item))
                    partial_len = len(nn)
            if synonyms_getter:
                for syn in (synonyms_getter(item) or []):
                    if _norm(syn) == q:
                        exact = (name, code_getter(item))
        if exact:
            return exact
        if partial:
            return partial
        return None, None
