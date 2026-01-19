#!/bin/bash
set -e

echo "Installing pre-compiled XFOIL..."

# Install XFOIL from Debian repository (it's already compiled and headless)
apt-get update
apt-get install -y xfoil

# Verify installation
which xfoil
xfoil -h || echo "XFOIL installed successfully"

echo "✅ XFOIL installation complete"