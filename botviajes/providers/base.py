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

    def search(self, origin: str, destination: str, date: str) -> List[Offer]:
        """Busca ofertas. `date` en formato YYYY-MM-DD. Devuelve lista de Offer."""
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
        exact, partial = None, None
        for item in candidates:
            name = name_getter(item)
            nn = _norm(name)
            if nn == q:
                return name, code_getter(item)
            if partial is None and (q in nn or nn in q) and len(q) >= 3:
                partial = (name, code_getter(item))
            if synonyms_getter:
                for syn in (synonyms_getter(item) or []):
                    if _norm(syn) == q:
                        exact = (name, code_getter(item))
        if exact:
            return exact
        if partial:
            return partial
        return None, None
