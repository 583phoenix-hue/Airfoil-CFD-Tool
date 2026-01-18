#!/bin/bash
# Install XFOIL on Linux - Fixed for Railway/Render
set -e

echo "Installing XFOIL dependencies..."
apt-get update
# Added libx11-dev which was missing
apt-get install -y gfortran build-essential wget libx11-dev

echo "Downloading XFOIL source..."
cd /tmp
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

echo "Compiling XFOIL..."
cd Xfoil/plotlib

# CRITICAL FIX: Tell the compiler where X11 is actually located
# We replace the hardcoded /usr/X11/include with the standard Linux path
sed -i 's|/usr/X11/include|/usr/include/X11|g' Makefile

make clean
make

cd ../orrs/bin
make clean
make osgen

cd ../..
cd src
make clean

# Remove the PLTOBJ link to avoid graphics issues in headless mode
sed -i 's/PLTOBJ = .*/PLTOBJ = /g' Makefile
make xfoil

echo "Installing XFOIL binary..."
cp xfoil /usr/local/bin/
chmod +x /usr/local/bin/xfoil

echo "XFOIL installed successfully!"
xfoil -h || echo "XFOIL is ready"