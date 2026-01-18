#!/bin/bash
set -e  # Exit immediately if a command fails

echo "Starting XFOIL Installation..."

# 1. Download and Extract
wget https://web.mit.edu/drela/Public/web/xfoil/xfoil6.99.tgz
tar -xzf xfoil6.99.tgz
cd Xfoil

# 2. PATCH THE MAKEFILES
# Fix the 'rm' commands so the build doesn't exit if a file is already gone
find . -name "Makefile*" -exec sed -i 's/bin\/rm /bin\/rm -f /g' {} +

# Replace Intel-specific flags (-fpe0, -CB) with GFortran equivalents
find . -name "Makefile*" -exec sed -i 's/-fpe0/-ffpe-trap=invalid,zero,overflow/g' {} +
find . -name "Makefile*" -exec sed -i 's/-CB/-fbounds-check/g' {} +

# Fix X11 search paths for modern Linux (Debian/Ubuntu)
find . -name "Makefile*" -exec sed -i 's/\/usr\/X11\/include/\/usr\/include\/X11/g' {} +
find . -name "Makefile*" -exec sed -i 's/\/usr\/X11\/lib/\/usr\/lib\/x86_64-linux-gnu/g' {} +

# 3. COMPILE PLOTLIB (Graphics library)
cd plotlib
make clean || true
make libPlt_gSP.a

# 4. COMPILE OSGEN (Aerostructural solver)
cd ../osgen
sed -i 's/FC = f77/FC = gfortran/g' Makefile
make clean || true
make osgen

# 5. COMPILE XFOIL
cd ../bin
sed -i 's/CC = cc/CC = gcc/g' Makefile
sed -i 's/FC = f77/FC = gfortran/g' Makefile
# Force the linker to find the math library and X11
sed -i 's/LIBS = -L\/usr\/lib\/x86_64-linux-gnu -lX11/LIBS = -lX11 -lm/g' Makefile

make clean || true
make xfoil

# 6. INSTALLATION
cp xfoil /usr/local/bin/
cp ../osgen/osgen /usr/local/bin/

echo "XFOIL installed successfully to /usr/local/bin/xfoil"