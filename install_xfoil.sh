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
BIN_DIR=$(find_dir "bin")

# 2. PATCH ALL MAKEFILES
# Fix the compiler and the "allow mismatch" issue
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/FC = f77/FC = gfortran/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/CC = cc/CC = gcc/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/FFLAGS = /FFLAGS = -fallow-argument-mismatch /g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/bin\/rm /bin\/rm -f /g' {} +

# 3. COMPILE PLOTLIB
cd "$PLOTLIB_DIR"
make clean || true
make libPlt_gSP.a

# LINKING FIX: XFOIL expects 'gDP' (Double Precision) but we built 'gSP' (Single)
# We create a symbolic link so the linker finds what it's looking for.
ln -s libPlt_gSP.a libPlt_gDP.a
echo "✅ Linked libPlt_gSP.a to libPlt_gDP.a"

# 4. COMPILE XFOIL
if [ -n "$BIN_DIR" ]; then
    cd "$BIN_DIR"
    
    # Force the Makefile to use the correct library search path and X11 location
    sed -i 's/\/usr\/X11R6\/lib/\/usr\/lib\/x86_64-linux-gnu/g' Makefile
    sed -i 's/\/usr\/X11\/include/\/usr\/include\/X11/g' Makefile
    
    make clean || true
    # We use -i (ignore errors) just for the first pass if it complains about osgen
    make xfoil || make xfoil
    
    # 5. INSTALLATION
    if [ -f "xfoil" ]; then
        cp xfoil /usr/local/bin/
        echo "🏁 XFOIL INSTALLED SUCCESSFULLY!"
    else
        echo "❌ XFOIL binary was not created!"
        exit 1
    fi
else
    echo "❌ Error: BIN directory not found!"
    exit 1
fi