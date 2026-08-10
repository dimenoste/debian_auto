#!/usr/bin/env bash

set -euo pipefail

echo "[*] Updating package lists..."
sudo apt-get update

echo "[*] Installing development tools..."
sudo apt-get install -y \
    build-essential \
    git \
    curl \
    wget \
    vim \
    python3 \
    python3-pip

echo "[+] Provisioning complete."

chmod +x scripts/provision.sh