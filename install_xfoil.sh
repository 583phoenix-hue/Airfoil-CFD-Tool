#!/bin/bash
# Install XFOIL on Linux

set -e

echo "Installing XFOIL dependencies..."
apt-get update
apt-get install -y gfortran build-essential wget

echo "Downloading XFOIL source..."
cd /tmp
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

echo "Compiling XFOIL..."
cd Xfoil
# Modify plot library settings for headless operation
cd plotlib
make clean
make
cd ..

cd orrs/bin
make clean  
make osgen
cd ../..

cd src
make clean
# Modify for no graphics
sed -i 's/PLTOBJ = .*/PLTOBJ = /g' Makefile
make xfoil

echo "Installing XFOIL binary..."
cp xfoil /usr/local/bin/
chmod +x /usr/local/bin/xfoil

echo "XFOIL installed successfully!"
xfoil -h || echo "XFOIL is ready"