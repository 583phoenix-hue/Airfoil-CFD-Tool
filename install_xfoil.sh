#!/bin/bash
# Install XFOIL on Linux - The "Intel to GNU" Fix
set -e

echo "Installing XFOIL dependencies..."
apt-get update
apt-get install -y gfortran build-essential wget libx11-dev

echo "Downloading XFOIL source..."
cd /tmp
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

echo "Patching Makefiles..."
cd Xfoil

# 1. Fix Plotlib (X11 path)
cd plotlib
sed -i 's|/usr/X11/include|/usr/include/X11|g' Makefile
make clean || true
make
cd ..

# 2. Fix ORRS (The 'ifort' error you just got)
cd orrs/bin
# Swap Intel compiler for GFortran and change flags
sed -i 's/FC = ifort/FC = gfortran/g' Makefile
sed -i 's/FTNFLAGS = -O -fpe0 -CB/FTNFLAGS = -O -std=legacy/g' Makefile
make clean || true
make osgen
cd ../..

# 3. Fix XFOIL Core
cd src
# Swap Intel compiler for GFortran and change flags
sed -i 's/FC = ifort/FC = gfortran/g' Makefile
sed -i 's/FTNFLAGS = -O -fpe0 -CB/FTNFLAGS = -O -std=legacy/g' Makefile
# Disable graphics for headless mode
sed -i 's/PLTOBJ = .*/PLTOBJ = /g' Makefile
# Linker flags fix
sed -i 's/LFLAGS = -Vaxlib/LFLAGS = /g' Makefile

make clean || true
make xfoil

echo "Installing XFOIL binary..."
cp xfoil /usr/local/bin/
chmod +x /usr/local/bin/xfoil

echo "XFOIL installed successfully!"
/usr/local/bin/xfoil -h || echo "XFOIL is ready"
