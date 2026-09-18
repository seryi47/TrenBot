import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from botviajes.providers import get_provider
print("VERIFICACIÓN Marsella — todos los vuelos, sin filtros")
for o,d,f in [("ALC","MRS","2026-10-09"),("MRS","ALC","2026-10-11"),("MRS","ALC","2026-10-12")]:
    print("\n── %s→%s %s ──" % (o,d,f))
    for x in sorted(get_provider("ryanair").search(o,d,f,adults=2), key=lambda z:z.departure or ""):
        print("   %s → %s   %8.2f €   %s   plazas %s" % (x.departure, x.arrival,
              x.price or 0, x.label, (x.raw or {}).get("plazas")))
