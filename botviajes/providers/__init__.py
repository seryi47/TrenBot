"""Registro de proveedores disponibles."""

from botviajes.providers.amadeus import AmadeusProvider
from botviajes.providers.iryo import IryoProvider
from botviajes.providers.ouigo import OuigoProvider
from botviajes.providers.renfe import RenfeProvider

# Instancias perezosas (se crean al primer uso para no cargar datos de más).
_REGISTRY = {}
_CLASSES = {
    "renfe": RenfeProvider,
    "ouigo": OuigoProvider,
    "iryo": IryoProvider,
    "amadeus": AmadeusProvider,
}

ALL = list(_CLASSES.keys())


def get_provider(name):
    name = name.lower()
    if name not in _CLASSES:
        raise KeyError("Proveedor desconocido: %s (usa uno de %s)" % (name, ALL))
    if name not in _REGISTRY:
        _REGISTRY[name] = _CLASSES[name]()
    return _REGISTRY[name]
