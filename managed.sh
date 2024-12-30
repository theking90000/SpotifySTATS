#!/bin/bash

# This script is used to start/stop the managed server

HOST=127.0.0.1:9322

if ! command -v docker  2>&1  >/dev/null
then
    echo "Docker is not installed. Please install Docker and try again."
    exit 1
fi

if ! command -v python3 2>&1  >/dev/null
then
    echo "Python3 is not installed. Please install Python3 and try again."
    exit 1
fi

if [ "$1" != "docker" ] && [ "$1" != "service" ]; then
    echo "Usage: $0 {docker|service} {start|stop} -f"
    exit 1
fi

MODE=$1

if [ "$MODE" = "service" ]; then
    echo "Installing Python dependencies..."

    if [ ! -d "venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv venv
        . venv/bin/activate
        pip install -r requirements_managed.txt
    else
        echo "Virtual environment already exists. Skipping..."
    fi
fi

DOCKER_IMAGE=spot_server:latest
WORKDIR=$(dirname "$(readlink -f "$0")")

echo "Checking for Docker image..."

if [ "$(docker images -q $DOCKER_IMAGE 2> /dev/null)" == "" ] || [ "$2" == "-f" ]; then
    echo "Downloading GeoLite2 database..."
    python3 download_geolite2.py
    echo "Building Docker image..."
    docker build -t $DOCKER_IMAGE .
else
    echo "Docker image already exists. Skipping build..."
fi

# Install systemctl
SERVICE_FILE=/etc/systemd/system/spotstats.service

if [ "$MODE" = "service" ]; then

if [ -f "$SERVICE_FILE" ]; then
    echo "Service already exists. Stopping service..."
else
echo "Installing service..."

sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Managed Python Application
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=$WORKDIR
EnvironmentFile=$WORKDIR/.env2
Environment="DOCKER_IMAGE=$DOCKER_IMAGE"
ExecStart=$WORKDIR/venv/bin/python -m gunicorn -b $HOST managed:app
Restart=always

[Install]
WantedBy=multi-user.target
EOL
fi

sudo systemctl daemon-reload

bash -c "cat > .env2" <<EOL
SPOTIFY_CLIENT_ID=<spotify_client_id>
SPOTIFY_CLIENT_SECRET=<spotify_client>
CLIENT_ID=<spotify_client_id>
CLIENT_SECRET=<spotify_client>
AUTHORIZATION_BASE_URL=https://accounts.spotify.com/authorize
TOKEN_URL=https://accounts.spotify.com/api/token
USER_URL=https://api.spotify.com/v1/me
SECRET_KEY=<unique_secret_key>
REDIRECT_URI=https://app-url/callback
EOL

echo 'Service installed'
echo 'Configure env variables in .env2 file'
fi

if [ "$MODE" = "service" ] && [ "$2" = "start" ]; then
    echo "Starting and enabling service..."
    sudo systemctl start spotstats.service
    sudo systemctl enable spotstats.service
elif [ "$MODE" = "service" ] && [ "$2" = "stop" ]; then
    echo "Stopping service..."
    sudo systemctl stop spotstats.service
    sudo systemctl disable spotstats.service
fi  