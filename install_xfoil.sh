#!/bin/bash
set -e 

echo "Starting XFOIL Installation..."

# 1. Download and Extract
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

# SMART PATH DETECTION
XFOIL_ROOT=$(find $(pwd) -iname "plotlib" -type d | head -n 1 | xargs dirname)
echo "✅ Found XFOIL root at: $XFOIL_ROOT"

# Helper function for case-insensitive dirs
find_dir() {
    find "$XFOIL_ROOT" -maxdepth 1 -iname "$1" -type d
}

PLOTLIB_DIR=$(find_dir "plotlib")
OSGEN_DIR=$(find_dir "osgen")
BIN_DIR=$(find_dir "bin")

# 2. PATCH ALL MAKEFILES (The "Relax" Patch)
# This is the critical line that fixes the 'Rank mismatch' error
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/bin\/rm /bin\/rm -f /g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/FC = f77/FC = gfortran/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/CC = cc/CC = gcc/g' {} +

# Inject the 'allow mismatch' flag into the Fortran flags (FFLAGS)
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/FFLAGS = /FFLAGS = -fallow-argument-mismatch /g' {} +
# Also fix other common XFOIL build traps
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/-fpe0/-ffpe-trap=invalid,zero,overflow/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/-CB/-fbounds-check/g' {} +

# 3. COMPILE PLOTLIB
cd "$PLOTLIB_DIR"
make clean || true
make libPlt_gSP.a

# 4. COMPILE OSGEN
if [ -n "$OSGEN_DIR" ]; then
    cd "$OSGEN_DIR"
    make clean || true
    make osgen || echo "OSGEN failed, but continuing..."
fi

# 5. COMPILE XFOIL
if [ -n "$BIN_DIR" ]; then
    cd "$BIN_DIR"
    # Fix X11 paths specifically for the main binary
    sed -i 's/\/usr\/X11\/include/\/usr\/include\/X11/g' Makefile
    sed -i 's/\/usr\/X11\/lib/\/usr\/lib\/x86_64-linux-gnu/g' Makefile
    # Ensure math library is linked
    sed -i 's/LIBS = /LIBS = -lm /g' Makefile
    
    make clean || true
    make xfoil
    
    # 6. INSTALLATION
    cp xfoil /usr/local/bin/
    echo "🏁 XFOIL installed successfully!"
else
    echo "❌ Error: BIN directory not found!"
    exit 1
fi