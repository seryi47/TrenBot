# BotViajes 🚆✈️🔔

Vigila la disponibilidad de billetes (trenes y vuelos) y **te avisa por Telegram
+ Mac** en cuanto aparece una plaza — ideal para trenes agotados que dependen de
cancelaciones de última hora.

- Consulta los backends reales de cada operador (no simula nada).
- Varias rutas a la vez, filtro por hora y por precio máximo.
- Sondeo configurable (por defecto **cada 30 s**) y aviso repetido (**cada 10 s**)
  mientras haya plaza, hasta que pulses `/stop`.
- Dos formas de usarlo: un **archivo de config** o un **bot de Telegram interactivo**.

> Uso personal. No abuses de la frecuencia: sondear demasiado rápido puede hacer
> que un operador te limite o bloquee la IP. 30 s es un buen equilibrio.

## Operadores soportados

| Operador | Estado | Cómo funciona |
|---|---|---|
| **Renfe** | ✅ Probado | Backend de venta (protocolo DWR). AVE, Alvia, MD, Avlo… con disponibilidad real. |
| **Ouigo** España | ✅ Probado | API de su web (token + `journeysearch`). |
| **Iryo** (ILSA) | 🧪 Experimental | Sin backend público conocido. Adaptador preparado, pendiente de implementar (ver más abajo). |
| **Vuelos** (Amadeus) | ✅ Listo (requiere API key gratis) | Amadeus Self-Service Flight Offers Search. Códigos IATA. |

## Instalación

```sh
cd ~/Desktop/BotViajes
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Configura tus secretos:

```sh
cp .env.example .env            # pega tu token y chat_id de Telegram
cp config.example.yaml config.yaml   # define qué rutas vigilar
```

### Telegram (obligatorio)
1. Abre **@BotFather** en Telegram → `/newbot` → te da el **token**.
2. Abre tu bot y pulsa **Start** (o envíale cualquier mensaje).
3. Abre **@userinfobot** → te dice tu **chat id**.
4. Pega ambos en `.env`.

Comprueba que llega:
```sh
./venv/bin/python run.py --test-telegram
```

### Vuelos con Amadeus (opcional)
Alta gratis en <https://developers.amadeus.com> → crea una app → copia
*API Key* y *Secret* en `.env` (`AMADEUS_API_KEY`, `AMADEUS_API_SECRET`).
El entorno `test` es gratis pero con datos limitados; para tiempo real fino
cambia `AMADEUS_ENV=production` (requiere activar la app en producción).

## Uso

### Modo A — archivo de config (`run.py`)
Edita `config.yaml` con tus rutas y lanza:

```sh
./venv/bin/python run.py            # vigilancia continua
./venv/bin/python run.py --once     # una comprobación y muestra el estado
```

### Modo B — bot interactivo de Telegram (`bot.py`)
Arranca el bot y gestiona las vigilancias chateando:

```sh
./venv/bin/python bot.py
```

Comandos:
```
/vigilar <proveedores>; <origen>; <destino>; <fecha>; [hora]; [precio_max]
/lista                 ver rutas vigiladas
/borrar <id>           quitar una ruta
/stop                  callar los avisos que están sonando (sigue vigilando)
/ayuda
```

Ejemplos (los campos se separan con `;` porque los nombres llevan espacios):
```
/vigilar renfe; Alicante; Albacete; 24/07/2026; 16:55
/vigilar trenes; Madrid; Valencia; 10/08/2026; ; 30
/vigilar amadeus; MAD; BCN; 15/08/2026
```
`trenes` = renfe + ouigo + iryo. Hora vacía = cualquier tren.

> Los dos modos comparten la misma watchlist (`watches.json`) y puedes usarlos a la vez.

### Dejarlo corriendo (que sobreviva a cerrar la terminal)
```sh
cd ~/Desktop/BotViajes
nohup ./venv/bin/python bot.py >> botviajes.log 2>&1 &
tail -f botviajes.log     # ver actividad
pkill -f bot.py           # pararlo
```

### En la nube 24/7 SIN TARJETA (GitHub Actions) ✅ en uso
El repo trae un workflow (`.github/workflows/vigilar.yml`) que vigila **cada 60 s**
en los servidores de GitHub, gratis y sin tarjeta. Cada ejecución es un job largo
que sondea en bucle ~5h33m; un `cron` de respaldo cada 5 min + la regla de
concurrencia relevan al siguiente job casi sin huecos.

- **Requiere repo PÚBLICO** (los minutos de Actions son ilimitados en público).
  Los *secrets* siguen siendo privados aunque el repo sea público.
- **Secretos** (repo → *Settings → Secrets and variables → Actions*):
  `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
- **Qué vigila:** el archivo **`watches.yaml`** (versionado, sin secretos). Edítalo
  en github.com (✏️ → *Commit*) o en local + `git push`.
- **⚠️ Aplicar cambios al momento:** el job en curso ya cargó `watches.yaml` al
  arrancar, así que un cambio no surte efecto hasta el siguiente relevo (hasta
  ~5h). Para aplicarlo ya: *Actions → run en curso → Cancel*; el siguiente
  arranca en ≤5 min con la watchlist nueva.
- **Velocidad:** baja `LOOP_INTERVAL` a `"30"` en el workflow para sondear cada 30 s.
- **Forzar/relanzar:** *Actions → Vigilar billetes → Run workflow*.

Límites honestos: es un uso **agresivo** de Actions (job casi 24/7, zona gris de
sus términos); GitHub **desactiva** los cron tras 60 días sin actividad en el repo
(haz un push de vez en cuando) y podría limitarlo si detecta abuso. Sin bot
interactivo aquí (rutas por archivo).

### En la nube 24/7 y gratis (Oracle Cloud Always Free)
Guía completa paso a paso: **[DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)**
(VM gratis para siempre + servicio `systemd` que arranca solo). Los avisos de
Mac se desactivan en servidor (`MAC_ALERTS=0`); el canal es Telegram.

## Cómo detecta "sin plazas"
En Renfe, un tren puede estar `completo=false` pero con `soloPlazaH=true`: solo
queda la plaza reservada para movilidad reducida. Eso es lo que la web muestra
como *"tren completo, sin plazas disponibles"*. El aviso salta cuando se libera
una plaza normal. En Ouigo/Amadeus, disponible = el viaje aparece con precio.

## Arquitectura

```
botviajes/
  models.py            # Offer (una oferta de viaje)
  notifier.py          # avisos: Telegram + Mac (sonido/voz/notificación/abre web)
  engine.py            # watchlist, sondeo, avisos repetidos, /stop, persistencia
  providers/
    base.py            # interfaz Provider + resolución de estaciones
    renfe.py           # ✅
    ouigo.py           # ✅
    iryo.py            # 🧪 stub
    amadeus.py         # ✈️ vuelos
data/                  # tablas de estaciones (Renfe, Ouigo)
run.py                 # modo config
bot.py                 # modo bot interactivo
```

### Añadir un proveedor (p. ej. completar Iryo)
1. Abre <https://iryo.eu>, busca un trayecto y mira en **DevTools → Network** la
   petición real de búsqueda (URL, cabeceras y payload JSON).
2. Copia `providers/iryo.py` y rellena `search()` para llamar a ese endpoint y
   devolver una lista de `Offer` (con `available=True/False`).
3. Ya está registrado en `providers/__init__.py`.

## Créditos
- [emartinez-dev/renfe-bot](https://github.com/emartinez-dev/renfe-bot) (MIT) — método DWR de Renfe.
- [RicardoAlegreMiranda/ouigo](https://github.com/RicardoAlegreMiranda/ouigo) (MIT) — API de Ouigo España.

Licencia MIT. Uso personal y responsable.
