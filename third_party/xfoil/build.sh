#!/bin/sh
# Builds XFOIL 6.996 (graphics off) into ./xfoil. Needs gfortran and gcc.
# Used by Dockerfile.backend; works the same on any Linux/macOS machine.
set -e
cd "$(dirname "$0")"
rm -rf build && mkdir build && cd build
FFLAGS="-O2 -std=legacy -w"
for f in xfoil xpanel xoper xtcam xgdes xqdes xmdes xsolve xbl xblsys xpol xplots \
         pntops xgeom xutils modify blplot polplt aread naca spline plutil iopol \
         gui sort dplot profil userio frplot0; do
  gfortran -c $FFLAGS -I../src "../src/$f.f" -o "$f.o"
done
gcc -c -O2 ../plot_stubs.c -o plot_stubs.o
gfortran -o ../xfoil ./*.o
cd .. && rm -rf build
echo "Built $(pwd)/xfoil"
