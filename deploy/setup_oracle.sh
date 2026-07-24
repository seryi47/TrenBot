#!/usr/bin/env bash
# Instalador para una VM Ubuntu (Oracle Always Free).
# Ejecutar desde la raíz del proyecto:  bash deploy/setup_oracle.sh
set -e

echo "==> Instalando dependencias del sistema..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git

echo "==> Creando entorno virtual e instalando dependencias de Python..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo
echo "==> Casi listo. Faltan tus secretos:"
echo "    1) cp .env.example .env        # y pega TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID"
echo "       (en servidor pon MAC_ALERTS=0 y OPEN_BROWSER=0)"
echo "    2) cp config.example.yaml config.yaml   # define tus rutas"
echo "    3) Prueba:  ./venv/bin/python run.py --test-telegram"
echo "    4) Instala el servicio (ver DEPLOY_ORACLE.md):"
echo "       sudo cp deploy/botviajes.service /etc/systemd/system/"
echo "       sudo systemctl daemon-reload && sudo systemctl enable --now botviajes"
