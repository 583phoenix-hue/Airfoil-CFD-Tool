#!/bin/bash
set -e 

echo "Starting XFOIL Installation..."

# 1. Download and Extract
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

# SMART PATH DETECTION: Find where the 'plotlib' folder actually is
XFOIL_ROOT=$(find $(pwd) -name "plotlib" -type d | head -n 1 | xargs dirname)

if [ -z "$XFOIL_ROOT" ]; then
    echo "Error: Could not find Xfoil source directory structure."
    exit 1
fi

echo "Found XFOIL root at: $XFOIL_ROOT"

# 2. PATCH THE MAKEFILES
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/bin\/rm /bin\/rm -f /g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/-fpe0/-ffpe-trap=invalid,zero,overflow/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/-CB/-fbounds-check/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/\/usr\/X11\/include/\/usr\/include\/X11/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/\/usr\/X11\/lib/\/usr\/lib\/x86_64-linux-gnu/g' {} +

# 3. COMPILE PLOTLIB
cd "$XFOIL_ROOT/plotlib"
make clean || true
make libPlt_gSP.a

# 4. COMPILE OSGEN
cd "$XFOIL_ROOT/osgen"
sed -i 's/FC = f77/FC = gfortran/g' Makefile
make clean || true
make osgen

# 5. COMPILE XFOIL
cd "$XFOIL_ROOT/bin"
sed -i 's/CC = cc/CC = gcc/g' Makefile
sed -i 's/FC = f77/FC = gfortran/g' Makefile
# Fix linking: move -lX11 and -lm to the end of the line
sed -i 's/LIBS = -L\/usr\/lib\/x86_64-linux-gnu -lX11/LIBS = -lX11 -lm/g' Makefile

make clean || true
make xfoil

# 6. INSTALLATION
cp "$XFOIL_ROOT/bin/xfoil" /usr/local/bin/
cp "$XFOIL_ROOT/osgen/osgen" /usr/local/bin/

echo "XFOIL installed successfully!"