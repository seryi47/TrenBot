"""Modelos de datos comunes a todos los proveedores."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Offer:
    """Un viaje concreto ofertado por un proveedor (tren o vuelo)."""

    provider: str                 # "renfe", "ouigo", "iryo", "amadeus"
    origin: str                   # nombre legible del origen
    destination: str              # nombre legible del destino
    date: str                     # fecha de salida, formato YYYY-MM-DD
    departure: str                # hora de salida "HH:MM"
    arrival: str = ""             # hora de llegada "HH:MM" (si se conoce)
    label: str = ""               # tipo de tren / nº de vuelo / clase
    price: Optional[float] = None # precio mínimo en EUR (None si no hay)
    available: bool = False       # ¿se puede comprar ahora mismo?
    buy_url: str = ""             # enlace para comprar
    raw: dict = field(default_factory=dict, repr=False)  # datos crudos del proveedor

    def key(self) -> str:
        """Identificador estable de esta oferta (para deduplicar avisos)."""
        return "%s|%s|%s|%s|%s" % (
            self.provider, self.origin, self.destination, self.date, self.departure
        )

    def price_str(self) -> str:
        return ("%.2f €" % self.price) if self.price is not None else "—"

    def __str__(self) -> str:
        estado = "✅" if self.available else "🔴"
        return "%s %s  %s→%s  %s  %s  %s" % (
            estado, self.departure, self.origin, self.destination,
            self.label, self.price_str(), self.provider,
        )
