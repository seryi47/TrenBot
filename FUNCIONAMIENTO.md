# Cómo funciona BotViajes

Documento de referencia: qué hace el bot, cómo está montado, qué te manda y
por qué, y dónde están las trampas. Si vuelves a esto dentro de seis meses,
esto es lo que hay que leer primero.

---

## 1. En una frase

Cada 15 minutos consulta el precio real de 14 vuelos concretos en los sistemas
de venta de Ryanair y Wizz Air, te avisa por Telegram cuando alguno baja, y
publica un panel web con las combinaciones de viaje que salen a cuenta.

**Corre solo en la nube.** No hace falta tener el ordenador encendido.

---

## 2. El circuito completo

```
   GitHub Actions  (vigilar.yml, cron cada 5 min, jobs de ~5 h 33 min)
          │
          │  python -u run.py --loop
          ▼
   ┌──────────────────────────────────────────┐
   │  Motor (botviajes/engine.py)             │
   │   · recorre watches.yaml                 │
   │   · pregunta el precio a cada proveedor  │
   │   · decide si hay que avisar             │
   └───────┬───────────────────────┬──────────┘
           │                       │
           ▼                       ▼
     Telegram                 historico.json
     (avisos)                 web/datos.json
                                    │
                                    │  git commit + push
                                    ▼
                              Vercel (conectado al repo)
                                    │
                                    ▼
                        viaje-octubre.vercel.app
```

La clave del montaje: **el propio commit del bot dispara el despliegue de la
web**. No hay token de Vercel en ninguna parte, y no depende del Mac.

---

## 3. Las piezas

### El paquete `botviajes/`

| Fichero | Qué hace |
|---|---|
| `engine.py` | El motor. Recorre las rutas, decide cuándo avisar y escribe el histórico. |
| `providers/ryanair.py` | Lee precios de Ryanair (API de disponibilidad de su web). |
| `providers/wizz.py` | Lee precios de Wizz Air (`be.wizzair.com`). |
| `providers/renfe.py`, `ouigo.py`, `iryo.py` | Trenes. Siguen ahí, no se usan en este viaje. |
| `providers/amadeus.py` | Sin usar: las *low cost* no publican en Amadeus. |
| `combinador.py` | Cruza un vuelo suelto con las combinaciones de viaje. |
| `notifier.py` | Envío a Telegram (y avisos de Mac cuando corre en local). |
| `fx.py` | Pasa a euros los precios en moneda extranjera (cambio del BCE). |
| `commands.py` | Comandos de Telegram: `/precios`, `/lista`, `/estado`… |

### Los scripts de la raíz

| Fichero | Para qué |
|---|---|
| `run.py --loop` | **Lo que ejecuta la nube.** Bucle de vigilancia + comandos. |
| `run.py --once` | Una pasada y enseña el estado. Útil para probar a mano. |
| `monitor.py` | Equivalente para ejecutar en el Mac. **Normalmente parado**: tenerlo a la vez que la nube duplicaría avisos. |
| `actualizar_web.py` | Genera `web/datos.json` con los precios que ya tiene el bot. |
| `configurar_vigilancia.py` | Deja `watches.json` listo con las rutas del viaje. |
| `resumen_telegram.py` | Manda el resumen completo a mano. |
| `probar_avisos.py` | **Las pruebas.** Seis casos, todos deben salir en verde. |

### Los datos

| Fichero | Quién lo escribe | Va al repo |
|---|---|---|
| `watches.yaml` | tú (o el bot desde Telegram) | sí |
| `watches.json` | el motor | **no** (privado) |
| `historico.json` | el motor | sí |
| `avisos.json` | el motor | sí |
| `rutas.json` | tú | sí |
| `web/datos.json` | `actualizar_web.py` | sí |
| `data/*_version.json` | los proveedores | sí |
| `data/wizz_horarios.json` | el proveedor de Wizz | sí |
| `.env`, `config.yaml` | tú | **no** (secretos) |

> `watches.json` está excluido a propósito. Por eso el histórico vive aparte en
> `historico.json`: si no, la nube perdería la memoria de precios en cada
> relevo del job.

---

## 4. Qué te llega por Telegram

### 🟢 Precio mínimo hasta ahora
El vuelo está en lo más barato que se ha visto. **Es la señal de compra.**

### 📉 Ha bajado un poco
Bajada de 3 € o más que no llega a ser mínimo. Incluye el contexto: entre qué
precios se ha movido y cómo va respecto al primer día. *Un "ha bajado" a secas
engaña: muchas veces es un rebote dentro de una subida.*

### 🎯 Ha entrado en tu objetivo
El precio ha cruzado el `max_price` de esa ruta.

### ⚠️ Me he quedado sin datos
Una ruta que antes daba precio lleva **3 consultas seguidas** sin dar nada. Un
solo mensaje para todas las rutas afectadas, nombrando la aerolínea.

### 👋 Resumen del día
Una vez cada 20 h, con la mejor combinación. **Si un día no llega, algo va
mal**: es la única forma de distinguir "no hay novedades" de "el bot está
muerto".

### Todos los avisos de vuelo incluyen

- Hora de salida y de llegada, **indicando de qué país es cada una** (en una
  vuelta, la salida no es hora española).
- Duración real del vuelo, con el huso horario aplicado.
- El **viaje completo** al que pertenece: los dos vuelos con su precio, su
  rango histórico, las plazas que quedan, el trayecto por tierra y **un enlace
  de compra por cada vuelo**.

### Reglas de silencio

| Situación | Comportamiento |
|---|---|
| Entra en objetivo | avisa |
| Sigue al mismo precio | calla |
| **Baja todavía más** | **avisa** |
| Sube un poco sin salirse | calla |
| Se sale y vuelve a entrar | avisa |
| Misma ceguera | 1 aviso cada 12 h |

El estado vive en `avisos.json`, que la nube commitea: así el silencio
sobrevive al relevo del job.

---

## 5. Cómo se leen los precios (y las trampas)

### Ryanair

`GET https://www.ryanair.com/api/booking/v4/es-es/availability`

- Exige las cabeceras `client: desktop` y `client-version`. Sin ellas: **409**.
- La `client-version` tiene que ser **la exacta** de su web: ni más alta ni más
  baja. La suben cada pocos días. El bot la lee de un comentario del HTML de su
  página de reservas (`<!-- Desktop version: 3.213.1 -->`), la cachea en
  `data/ryanair_version.json` y la revalida ante cada 409.
- Devuelve la duración del vuelo ya calculada.
- Cotiza en la moneda del país **de salida** (Pardubice manda coronas checas).

### Wizz Air

`POST https://be.wizzair.com/{versión}/Api/search/timetable`

- Exige la cabecera `X-RequestVerificationToken`, cuyo valor sale de la cookie
  del mismo nombre que entrega `POST /Api/asset/culture`. Sin ella: **400
  InvalidProtocol**.
- La versión va en la URL. **Al jubilar una versión responden 503, no 404**, así
  que la detección salta ante cualquier fallo (400, 404, 429, 503). Se cachea en
  `data/wizz_version.json`.
- `flightList` admite **dos entradas como máximo**.
- **El precio llega en la moneda de la estación de salida del PRIMER tramo.**
  Poniendo delante un tramo que sale de zona euro, todo llega en euros.
- ⚠️ **`priceType: "checkPrice"` viene con importe 0.** No es gratis: es que no
  hay precio publicado. Se marca como *orientativo*, no dispara avisos y en la
  web sale con `≈`.
- No da hora de llegada por esta vía: se cachean las conocidas en
  `data/wizz_horarios.json` y el resto se calcula por distancia y huso horario.
- `/search/search` da más detalle pero se satura enseguida (429); tras un fallo
  se aparca 30 minutos.

### Reglas que valen para los dos

- **Un importe de 0 o negativo nunca es una tarifa.** Se descarta siempre.
- El precio se busca **para 2 pasajeros**: en *low cost* el precio por persona
  sube si la tarifa barata no tiene dos asientos.
- Sondeo **cada 15 minutos por ruta**. Más rápido y cortan con 429/503.
- Los datos del vuelo (horas, duración, plazas, enlace) se refrescan en cada
  sondeo; el precio solo entra en el histórico si cambia de verdad.

---

## 6. El viaje de octubre

Alicante ida y vuelta, 2 personas, **solo vuelos directos**:

1. Ida el **8 de octubre a partir de las 20:00**, o el **9 a cualquier hora**.
2. Vuelta el **11 a cualquier hora**, o el **12 aterrizando antes de las 18:00**.
3. Máximo **160 € por persona** sumando ida y vuelta.
4. **Dos países**, con al menos un día para el segundo.
5. Si sales el 9, **aterrizar antes de las 20:00**: llegar de noche pierde el día.

Las combinaciones están en `rutas.json`, con sus tramos, el trayecto por tierra
y el día a día. La conectividad terrestre está **verificada con horarios
reales**, no estimada: la distancia en línea recta miente (Marsella-Turín
parecían 4,8 h y son 6h10 por los Alpes).

---

## 7. Operativa

```sh
# ver el estado ahora mismo
./venv/bin/python run.py --once

# las pruebas (deben salir 6 en verde)
./venv/bin/python probar_avisos.py

# regenerar la web a mano
./venv/bin/python actualizar_web.py

# mandarte el resumen completo
./venv/bin/python resumen_telegram.py
```

**Cambiar qué se vigila:** edita `watches.yaml` y haz push. El job en curso ya
cargó la lista al arrancar, así que el cambio entra en el siguiente relevo
(hasta 5 h). Para aplicarlo ya: cancela el run en *Actions* y lanza otro.

**Desde Telegram:** `/precios`, `/lista`, `/estado`, `/vigilar`, `/borrar`,
`/pausa`, `/seguir`, `/apagar si`.

---

## 8. Qué se auto-repara y qué no

| Si pasa esto… | El bot… |
|---|---|
| Ryanair sube su `client-version` | la lee de su web y sigue ✅ |
| Wizz jubila su versión de API | la detecta y sigue ✅ |
| Llega un precio de 0 | lo descarta ✅ |
| Wizz no publica precio | lo marca orientativo, sin avisar ✅ |
| Un destino de Telegram desaparece | lo descarta tras avisar una vez ✅ |
| GitHub corta el job a las 5 h 33 | releva al siguiente ✅ |
| Una ruta deja de dar datos | te avisa a la 3ª consulta ✅ |
| El bot entero se muere | **falta el resumen diario** ✅ |

**El límite honesto:** esto cubre *datos que faltan* y *datos imposibles*. No
puede detectar un dato plausible pero equivocado. Para eso están los guardas
concretos que se han ido añadiendo, y cada uno salió de un fallo real.

---

## 9. Si algo va mal

| Síntoma | Dónde mirar |
|---|---|
| No llega nada en todo el día | *Actions* → ¿hay job corriendo? ¿el workflow está activo? |
| Un vuelo sin datos | El log del job: ¿`409`? ¿`503`? Suele ser un cambio de versión. |
| Precios raros o a 0 | `historico.json`: no debe haber ningún valor ≤ 0. |
| La web no se actualiza | ¿Commiteó el bot? ¿Vercel sigue conectado al repo? |
| Avisos repetidos | `avisos.json`: ahí está el control de silencio. |

Los logs del job están en *Actions → Vigilar billetes → run → Vigilar en bucle*.
Salen sin búfer (`PYTHONUNBUFFERED`), así que se ven en tiempo real.

---

## 10. Histórico de fallos encontrados

Se dejan apuntados porque cada uno costó encontrarlo y ninguno era evidente:

1. **Ryanair 409** — faltaban las cabeceras `client` / `client-version`.
2. **Wizz 400 InvalidProtocol** — faltaba el token de verificación.
3. **Precios en moneda local** — Wizz y Ryanair cotizan en la divisa del país de salida.
4. **Wizz `checkPrice` = 0 €** — provocó un aviso falso de "billetes a 0 €".
5. **Ryanair subió a 3.213.1** — la versión estaba escrita a fuego.
6. **Wizz jubiló la 29.15.1 con un 503** — la detección solo saltaba con 404.
7. **La nube borraba el histórico** — las rutas nacían después de leerlo.
8. **El log del job salía vacío** — Python almacenaba la salida en un búfer.
9. **Avisos cada 15 minutos** — no había control de repetición.
10. **El silencio tapaba las bajadas posteriores** — se corrigió pasándose de frenada.
11. **Falso "1 vuelo sin datos"** — se contaban los silencios de objetivo como ceguera.
12. **Datos del vuelo a medias** — dos filtros salían antes de anotarlos.
