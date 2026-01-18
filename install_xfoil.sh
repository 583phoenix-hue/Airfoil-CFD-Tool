#!/bin/bash
set -e 

echo "Starting XFOIL Installation..."

# 1. Download and Extract
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz

# SMART PATH DETECTION: Find where the source actually lives
# We look for 'plotlib' and get its parent directory
XFOIL_ROOT=$(find $(pwd) -iname "plotlib" -type d | head -n 1 | xargs dirname)

if [ -z "$XFOIL_ROOT" ]; then
    echo "❌ Error: Could not find Xfoil source directory."
    ls -R
    exit 1
fi

echo "✅ Found XFOIL root at: $XFOIL_ROOT"

# Helper function to find subdirectories case-insensitively
find_dir() {
    find "$XFOIL_ROOT" -maxdepth 1 -iname "$1" -type d
}

PLOTLIB_DIR=$(find_dir "plotlib")
OSGEN_DIR=$(find_dir "osgen")
BIN_DIR=$(find_dir "bin")

echo "Directories found: PLOT=$PLOTLIB_DIR, OSGEN=$OSGEN_DIR, BIN=$BIN_DIR"

# 2. PATCH ALL MAKEFILES IN THE TREE
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/bin\/rm /bin\/rm -f /g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/-fpe0/-ffpe-trap=invalid,zero,overflow/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/-CB/-fbounds-check/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/\/usr\/X11\/include/\/usr\/include\/X11/g' {} +
find "$XFOIL_ROOT" -name "Makefile*" -exec sed -i 's/\/usr\/X11\/lib/\/usr\/lib\/x86_64-linux-gnu/g' {} +

# 3. COMPILE PLOTLIB
cd "$PLOTLIB_DIR"
make clean || true
make libPlt_gSP.a

# 4. COMPILE OSGEN
if [ -n "$OSGEN_DIR" ]; then
    cd "$OSGEN_DIR"
    sed -i 's/FC = f77/FC = gfortran/g' Makefile
    make clean || true
    make osgen
else
    echo "⚠️ Warning: OSGEN directory not found, skipping..."
fi

# 5. COMPILE XFOIL
if [ -n "$BIN_DIR" ]; then
    cd "$BIN_DIR"
    sed -i 's/CC = cc/CC = gcc/g' Makefile
    sed -i 's/FC = f77/FC = gfortran/g' Makefile
    # Fix linking: use -lm for math library and link X11
    sed -i 's/LIBS = -L\/usr\/lib\/x86_64-linux-gnu -lX11/LIBS = -lX11 -lm/g' Makefile
    
    make clean || true
    make xfoil
    
    # 6. INSTALLATION
    cp xfoil /usr/local/bin/
    [ -f "$OSGEN_DIR/osgen" ] && cp "$OSGEN_DIR/osgen" /usr/local/bin/
    echo "🏁 XFOIL installed successfully!"
else
    echo "❌ Error: BIN directory (XFOIL source) not found!"
    exit 1
fi