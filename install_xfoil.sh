#!/bin/bash
# Install XFOIL on Linux - Fixed for "Clean" errors
set -e

echo "Installing XFOIL dependencies..."
apt-get update
apt-get install -y gfortran build-essential wget libx11-dev

echo "Downloading XFOIL source..."
cd /tmp
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

echo "Compiling XFOIL..."
cd Xfoil/plotlib
sed -i 's|/usr/X11/include|/usr/include/X11|g' Makefile
# We use || true to prevent the script from stopping if 'clean' finds nothing to delete
make clean || true
make

echo "Building ORRS..."
cd ../orrs/bin
# Fix for the specific error you just got: ignore clean errors
make clean || true
make osgen

echo "Building XFOIL core..."
cd ../..
cd src
make clean || true

# Disable graphics to make it a 'headless' server version
sed -i 's/PLTOBJ = .*/PLTOBJ = /g' Makefile
# XFOIL uses an old Fortran style; we add a flag to allow it
sed -i 's/FTNFLAGS = -O/FTNFLAGS = -O -std=legacy/g' Makefile

make xfoil

echo "Installing XFOIL binary..."
cp xfoil /usr/local/bin/
chmod +x /usr/local/bin/xfoil

echo "XFOIL installed successfully!"
xfoil -h || echo "XFOIL is ready"