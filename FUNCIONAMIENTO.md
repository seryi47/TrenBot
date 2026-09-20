# Cómo funciona BotViajes

Documento de referencia: qué hace el bot, cómo está montado, qué te manda y
por qué, y dónde están las trampas. Si vuelves a esto dentro de seis meses,
esto es lo que hay que leer primero.

---

## 1. En una frase

Cada 15 minutos consulta el precio real de los vuelos listados en
`watches.yaml` en los sistemas de venta de Ryanair y Wizz Air, te avisa por Telegram cuando alguno baja, y
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
| `publicar.py` | Sube los datos al repo, que es lo que hace desplegar a Vercel. |
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

**No se manda si el viaje es imposible.** Que baje 5 € un vuelo cuyo mejor viaje
cuesta el doble del tope no es información útil. Se calla si la combinación más
barata que lo incluye pasa del 125 % del tope, salvo que sea mínimo histórico:
eso sí dice algo.

### 🎯 Ha entrado en tu objetivo
El precio ha cruzado el `max_price` de esa ruta.

### ⚠️ Me he quedado sin datos
Una ruta que antes daba precio lleva **3 consultas seguidas** sin dar nada. Un
solo mensaje para todas las rutas afectadas, nombrando la aerolínea.

### 👋 Sigo vigilando
**Dos veces al día** (cada 12 h), con la mejor combinación del momento y cuántas
bajadas se han callado por ser ruido. **Si no llega, algo va mal**: es la única
forma de distinguir "no hay novedades" de "el bot está muerto". Se pasó de 20 h
a 12 porque, con el filtro de ruido, veinte horas de silencio no se distinguían
de una avería.

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
  hay **ninguna plaza a la venta**. Ese vuelo queda sin precio —ni el 0, ni el
  `originalPrice` de referencia, que no se puede comprar— y la web marca la
  combinación como *incompleta*.
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
3. Máximo **190 € por persona** sumando ida y vuelta.
4. **Dos países**, con al menos un día para el segundo.
5. Si sales el 9, **aterrizar antes de las 20:00**: llegar de noche pierde el día.
6. **Sin viajes por dentro**: cuanto menos transporte entre aeropuertos, mejor.

Quedan fuera por decisión del viaje: **Reino Unido, Irlanda, Alemania y España**.

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
| Wizz no publica precio | lo deja sin cifra, "sin plazas a la venta" ✅ |
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

### Nada puede quedarse colgado
Toda llamada a un proceso externo (git, la regeneración de la web, los avisos
del Mac) lleva **timeout**. Sin él, un `git push` esperando congelaría el bucle
para siempre y el bot dejaría de avisar **sin que nadie se entere**: el silencio
de una avería es idéntico al de "no hay novedades". Si algo tarda, se salta esa
vuelta y se reintenta en la siguiente.

Además, al entrar a publicar se comprueba si quedó un **rebase a medias**. Uno
interrumpido bloquea el repo: a partir de ahí ningún commit entra y la web se
congela en silencio mientras Telegram sigue funcionando — la avería más difícil
de ver. Si lo hay, se aborta solo.

La prueba 8 de `probar_avisos.py` recorre el código y falla si aparece un
proceso externo sin timeout, para que esto no vuelva a colarse.

### Cuando un vuelo se queda sin plazas
Wizz responde `priceType: checkPrice` con importe 0 cuando ese vuelo **no tiene
ninguna tarifa a la venta**. Deja un `originalPrice` de referencia que tampoco
sirve: no se puede comprar a ese precio.

El bot no enseña ninguna cifra. El vuelo queda como *sin plazas a la venta*, las
combinaciones que lo contienen salen **incompletas** (y ordenan al final, no al
principio), y el resumen de cada 12 h lo dice con la fecha del último precio
real. Saberlo **no** cuenta como quedarse ciego: es un dato, no una falta de
datos.

### ¿Nos sirven precios cacheados o "de bot"? (comprobado el 15-sep-2026)
Sospecha razonable, así que se midió en vez de suponerlo. `diagnostico.py` hace
las mismas consultas desde dos sitios y se compara.

**Resultado: los precios son reales y nadie nos discrimina.**

- Ryanair responde `x-cache: Miss from cloudfront` y `cache-control: no-store`
  en **todas** las peticiones: no hay caché de por medio. La misma consulta con
  cookies, sin cookies, con mercado `en-gb`, con parámetro anticaché aleatorio y
  con huella TLS de Safari devuelve **el mismo precio y las mismas plazas**.
- Desde la IP de casa (España) y desde la de GitHub (Azure) los cinco vuelos dan
  cifras **idénticas al céntimo**, incluida la misma falta de precio firme en
  Bratislava. Si nos sirvieran precios inflados por estar fichados, dos IPs sin
  relación no coincidirían.
- Los tipos de cambio se comprobaron contra el XML oficial del BCE: desvío
  **0,0000 %**.

**Lo que sí es cierto: Wizz nos tiene marcados.** `/search/search` devuelve 429
siempre — desde el Mac, desde la nube, con sesión virgen, calentando su web
antes y esperando 20 s. Y su web lanza un captcha de "Confirme que es humano" a
un navegador automatizado. No es un límite que se pueda esperar: es un bloqueo.

El bot ya lo esquiva cayendo a `/search/timetable`, que **sí funciona y da
precios firmes correctos**. Pero ese camino no trae una cosa: **las plazas que
quedan**. Por eso en los vuelos de Ryanair se ve "quedan 5" y en los de Wizz no.
Es la señal que avisa de que una tarifa va a subir, y en Wizz vamos a ciegas:
por eso el Gdansk de vuelta subió 10 € de golpe sin previo aviso.

Un detalle de divisa: Wizz cotiza distinto según el país de compra. El mismo
GDN→ALC vale 409 PLN (94,24 €) comprándolo en Polonia y 89,99 € comprándolo en
euros. El bot fuerza euros poniendo un tramo de zona euro primero en la consulta,
así que enseña la tarifa **más barata**, que es la que pagarías tú.

### ¿Y si comprar desde el otro país fuera más barato?
Wizz cotiza el mismo asiento en la divisa del país de salida y **no siempre al
mismo cambio**. El bot pide en euros, pero eso era una suposición, así que se
midió ruta por ruta (15-sep-2026):

| Ruta | En divisa local | En euros | Gana |
|---|---|---|---|
| ALC→GDN | 409 PLN = 94,24 € | 89,99 € | euros, +4,25 € |
| GDN→ALC | 409 PLN = 94,24 € | 89,99 € | euros, +4,25 € |
| BUD→ALC | 38 290 HUF = 104,61 € | 99,99 € | euros, +4,62 € |
| BTS→ALC | 124,99 € | 124,99 € | empate (Eslovaquia ya es euro) |

**En Ryanair no hay nada que rascar**: la divisa la fija el país del aeropuerto
de salida y el parámetro de mercado no cambia el precio. Comprobado en los 5
vuelos contra 8 mercados (`es-es`, `cs-cz`, `pl-pl`, `de-de`, `it-it`, `en-ie`,
`en-gb`, `hu-hu`): idéntico en todos.

Hoy el euro gana siempre, pero eso es una tarifa, no una ley. `divisas.py`
compara las dos divisas de cada ruta **una vez al día** desde el bucle y avisa si
alguna vez cambia. El umbral es del **3 %**: comparar al cambio del BCE engaña,
porque pagando en moneda extranjera el banco cobra su comisión (1,5-3 % es lo
normal), así que un ahorro menor que eso no es un ahorro. También se puede
lanzar a mano: `python divisas.py`.

### Qué combinación encabeza el resumen
Durante un tiempo el resumen se contradecía solo: anunciaba *"la más barata es
Bratislava + Praga, 167,92 €"* y dos líneas más abajo avisaba de que ese precio
no era firme. Elegía por precio y nada más.

Ahora encabeza **la más barata que se puede comprar de verdad**, y:

- las combinaciones con algún tramo sin plazas no compiten por el primer puesto:
  salen como *incompletas*;
- si la más barata obliga a un traslado y hay otra casi al mismo precio que no,
  se dice (*"por 2,06 € más, Gdansk te ahorra ese traslado"*). Ahorrar dos euros
  a cambio de tres horas de tren no es ahorrar;
- si **ninguna** tuviera precio firme, lo dice en vez de afirmar que se puede
  comprar.

### Nunca un precio que no se pueda comprar
Wizz marca algunos vuelos con `priceType: checkPrice`, manda `price.amount = 0`
y deja un `originalPrice` de referencia. El bot enseñaba ese `originalPrice`
como "precio orientativo" — **es un número que no se puede comprar**, así que
era inventárselo. Fuera. Ahora ese vuelo queda como lo que es: **sin plazas a la
venta**, sin cifra, y las combinaciones que lo contienen salen *incompletas*.

Comprobado antes de decidirlo: no hay precio ni pidiendo **1 solo pasajero**, ni
con tarifa de socio (WDC), y **la misma ruta sí da precio otros días**
(7-oct 69,99 € · 14-oct 89,99 €), así que no es un bloqueo nuestro.

### Cuántas plazas quedan, sin que Wizz lo diga
Ryanair publica `faresLeft`. Wizz bloquea con 429 el único endpoint que lo trae,
así que **se deduce**: Wizz vende por cubos de tarifa, y si pides más pasajeros
de los que quedan en el cubo barato, **el precio salta**.

    ALC→Gdansk   1:90  2:90  3:90 | 4:100 ... 8:115
                 └── quedan 3 asientos a 89,99 €

`plazas_restantes()` lo busca en binario: 3-4 consultas en vez de nueve.
Validado contra la escalera completa de las cinco rutas de Wizz: acierta las
cinco. Se recalcula cada 6 h, no en cada sondeo.

Con esto llega un aviso nuevo: **⏳ Quedan N plazas**, cuando bajan de 2. Es la
señal que faltaba — una tarifa no sube por sorpresa, sube cuando se agota su
cubo, y el Gdansk de vuelta subió 10 € de golpe justo por no tener este dato.
El filtro aquí es **más estricto** que en las bajadas: si el vuelo no forma parte
de ningún viaje que puedas hacer, que se agote da igual y no se avisa.

### El itinerario no repite trenes ni enlaces
Los traslados por tierra se pintaban dentro del bucle de vuelos usando la lista
entera, así que **cada tren salía una vez por cada vuelo**: el mismo trayecto
aparecía como *"y luego: Wrocław → Pardubice"* tras la ida y otra vez como
*"cómo llegas: Wrocław → Pardubice"* antes de la vuelta. Ahora cada traslado se
cuelga solo del vuelo al que sigue. Si hay dos seguidos se encadenan en una
línea (*"Viena → Praga → Pardubice · 5h00 en total"*).

El vuelo del aviso tampoco repite su enlace: ya lleva el botón grande al final.

### Barrido completo desde Alicante (18-sep-2026)
Se miraron **los 57 destinos directos** desde ALC de las dos compañías, no solo
los que ya estaban en la lista. Dos cosas que hay que saber para repetirlo:

- **El 409 de Ryanair miente.** `availability` responde `409 Availability
  declined` en cuanto se le insiste desde una IP, y ese 409 es idéntico al de
  "esa ruta no vuela ese día". El primer barrido dio por inexistentes 30 rutas
  que sí vuelan. Hay que filtrar antes con `timtbl/3/schedules`, que **no se
  bloquea** y dice día y hora exactos de cada vuelo del mes.
- **El bloqueo es por IP y solo afecta a quien barre.** Mientras el Mac estaba
  con 409, la nube seguía leyendo precios con normalidad. Por eso el barrido va
  en su propio workflow (`barrido.yml`), separado del bot.

Resultado: 18 de 42 destinos de Ryanair cumplen los horarios del viaje. Se
añadieron a vigilancia **Bucarest, Sofía y Katowice**, que no estaban y son las
tres más baratas sin ningún traslado por tierra.

La ida y la vuelta **pueden ser de compañías distintas**. Se calculó cruzando
todo (`research/cruzar.py`) y hoy solo sale una combinación mixta (Venecia, ida
Wizz + vuelta Ryanair): donde las dos compañías coinciden, una suele ser más
barata en ambos sentidos. La regla queda puesta para cuando cambie.

### El bot lee el precio de la AEROLÍNEA, no el del mercado
Pregunta a Ryanair y a Wizz cuánto cuestan **sus** billetes. Eso no es lo más
barato que existe: revendedores como Kiwi, Trip.com o BudgetAir suelen estar
**5-15 € por debajo** del precio oficial del mismo vuelo. Comprobado el
20-sep-2026: Wizz pedía 184,98 €/persona por Katowice (vuelos W61080/W61079) y
Kiwi vendía **esos mismos dos vuelos a 172 €**.

No se puede automatizar: Skyscanner lanza captcha a un navegador automatizado y
la API de Kiwi pide clave. Google Flights sí se deja (`research/mercado.py`),
pero da el total del viaje, no el desglose por revendedor.

**Conclusión práctica: antes de comprar, mira el mismo vuelo en un comparador.**
La web lo avisa. Lo que el bot hace bien es detectar *cuándo* un vuelo está
barato y avisarte; el último paso, quién te lo vende, es manual.

### Dos fallos del barrido, encontrados el 20-sep-2026
- **Las llegadas de madrugada colaban.** El filtro del día 9 aceptaba un vuelo
  que sale a las 22:00 y aterriza a la 01:05 del día siguiente, porque comparaba
  `"01:05" < "20:00"` como texto. Es justo el caso que la regla quiere evitar.
- **Una ida válida se perdía si su compañía no tenía vuelta.** El barrido
  descartaba el destino entero, lo que anula la regla de poder ir con una
  compañía y volver con otra. Así se escondió la ida de **Ryanair a Gdansk** del
  jueves 8 a las 20:10, que existe y cumple los horarios.

### El objetivo de un tramo no es noticia si el viaje es imposible
El aviso de "🎯 ha entrado en tu objetivo" **se saltaba el filtro de ruido**: lo
pasaban solo las bajadas. Por eso llegó un aviso de Linz a 116,99 € (objetivo
≤125) dentro de un viaje de 287,98 € por persona, muy por encima del tope.

Peor: ese total era falso. El **combinador sumaba el último precio conocido de
un vuelo sin plazas a la venta**, y ese precio ya no existe — la ida a
Bratislava contaba a 170,99 € cuando no se puede comprar a ningún precio.

Ahora un tramo en objetivo solo se avisa si forma parte de **al menos un viaje
comprable** y ese viaje no se dispara del tope, el mismo criterio que las
bajadas y las últimas plazas. Y los tramos sin venta no puntúan en ningún total:
su viaje sale *incompleto*, igual que en la web.
