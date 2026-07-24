# Desplegar BotViajes en Oracle Cloud (Always Free) 🆓☁️

Guía para dejar el bot corriendo 24/7 y gratis para siempre en una VM de Oracle.
No hace falta abrir ningún puerto: el bot solo hace conexiones **salientes**
(a Telegram y a los operadores).

---

## 1. Crear la cuenta y la VM

1. Regístrate en <https://www.oracle.com/cloud/free/> (pide tarjeta solo para
   verificar; los recursos **Always Free** no se cobran).
2. En la consola: **Compute → Instances → Create Instance**.
3. Configuración:
   - **Image:** Canonical **Ubuntu** 22.04/24.04.
   - **Shape:** pulsa *Change shape* → **Ampere (ARM)** si hay hueco, o el
     **VM.Standard.E2.1.Micro (AMD, 1 GB)** — este casi siempre está libre y le
     sobra al bot. Ambos son *Always Free eligible*.
   - **SSH keys:** *Generate a key pair* y **descarga la clave privada** (o pega
     tu clave pública).
4. **Create**. En un minuto tendrás una **IP pública**.

> Si el ARM da "Out of capacity", usa el micro AMD o prueba otra
> *Availability Domain* / región.

---

## 2. Conectarte por SSH

```sh
chmod 600 ~/Descargas/tu-clave.key
ssh -i ~/Descargas/tu-clave.key ubuntu@LA_IP_PUBLICA
```
(El usuario por defecto de la imagen Ubuntu es `ubuntu`.)

---

## 3. Traerte el código

El repo es **privado**, así que necesitas autenticarte. La forma más rápida es
un **token de acceso personal** de GitHub (permiso de solo lectura de código):

1. GitHub → *Settings → Developer settings → Personal access tokens →
   Fine-grained tokens* → *Generate*. Dale acceso **Read-only** a *Contents*
   del repo `TrenBot`. Copia el token.
2. En la VM:

```sh
git clone https://TU_TOKEN@github.com/seryi47/TrenBot.git
cd TrenBot
```

> Alternativa sin token: copia la carpeta desde tu Mac con
> `scp -i tu-clave.key -r ~/Desktop/BotViajes ubuntu@LA_IP:~/TrenBot`
> (pero recuerda que `.env` y `config.yaml` no se suben; los creas en el paso 5).

---

## 4. Instalar

```sh
bash deploy/setup_oracle.sh
```
Crea el `venv` e instala las dependencias.

---

## 5. Configurar tus secretos (en la VM)

```sh
cp .env.example .env
nano .env
```
Rellena y, **importante en servidor**, desactiva los avisos de Mac:
```
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id
MAC_ALERTS=0
OPEN_BROWSER=0
POLL_INTERVAL=30
ALERT_INTERVAL=10
```

```sh
cp config.example.yaml config.yaml
nano config.yaml     # define tus rutas (o gestiónalas luego desde el bot)
```

Prueba que Telegram llega:
```sh
./venv/bin/python run.py --test-telegram
```

---

## 6. Dejarlo como servicio (arranca solo y se reinicia si falla)

```sh
sudo cp deploy/botviajes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now botviajes
```

Comprobar y ver logs:
```sh
systemctl status botviajes
journalctl -u botviajes -f        # log en vivo
```

Ya está: escribe `/start` a tu bot en Telegram. Sobrevive a reinicios de la VM.

---

## Mantenimiento

| Acción | Comando |
|---|---|
| Ver logs en vivo | `journalctl -u botviajes -f` |
| Reiniciar | `sudo systemctl restart botviajes` |
| Parar | `sudo systemctl stop botviajes` |
| Actualizar código | `cd ~/TrenBot && git pull && sudo systemctl restart botviajes` |

> **Idle reclaim:** Oracle puede reclamar instancias Always Free muy inactivas.
> Este bot hace trabajo cada 30 s (CPU periódica), así que no debería
> considerarse inactivo, pero si algún día te la reclaman, basta con recrearla.

> **Frecuencia:** 30 s es agresivo. Para vigilancias de varios días, sube
> `POLL_INTERVAL` a 60 en el `.env` y `sudo systemctl restart botviajes`.
