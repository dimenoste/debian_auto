#!/usr/bin/env bash

set -euo pipefail

echo "[*] Updating package lists..."

sudo apt-get update

echo "[*] Installing development tools..."

sudo apt-get install -y \
    build-essential \
    git \
    openssh-client \
    curl \
    wget \
    vim \
    python3 \
    python3-pip \
    ca-certificates

echo "[*] Adding Docker's official GPG key..."

sudo install -m 0755 -d /etc/apt/keyrings

sudo curl -fsSL \
    https://download.docker.com/linux/debian/gpg \
    -o /etc/apt/keyrings/docker.asc

sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "[*] Adding Docker's official APT repository..."

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

echo "[*] Updating package lists with Docker repository..."

sudo apt-get update

echo "[*] Installing Docker..."

sudo apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

echo "[*] Starting Docker..."

sudo systemctl enable --now docker

echo "[*] Docker version:"
sudo docker --version

echo "[*] Docker Compose version:"
sudo docker compose version



echo "[*] Configure Git author identity from existing Git configuration:"
# Configure Git author identity from existing Git configuration
if [[ -n "${GIT_USER_NAME:-}" && -n "${GIT_USER_EMAIL:-}" ]]; then
    echo "[*] Configuring Git identity..."

    if git config --global user.name "$GIT_USER_NAME" &&
       git config --global user.email "$GIT_USER_EMAIL"; then
        echo "[+] Git identity configured."
    else
        echo "[!] Failed to configure Git identity. Skipping."
    fi
fi

echo "[+] Provisioning complete."