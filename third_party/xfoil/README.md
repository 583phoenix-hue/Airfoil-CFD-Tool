# XFOIL 6.996 (source)

The XFOIL source used by AeroLab's backend: XFOIL 6.996 by Mark Drela and
Harold Youngren (MIT), unmodified, taken from the source bundle published with
WebXFOIL (https://github.com/PR-DC/WebXFOIL, tag v0.1.1), which is also where
the browser build in `aerolab-web/public/xfoil/` comes from. Original
distribution: https://web.mit.edu/drela/Public/web/xfoil/

Only the files needed for the command-line program are kept (`src/`), plus
Drela's `version_notes.txt`. The plot library is replaced by the no-op
functions in `plot_stubs.c`, because AeroLab always runs XFOIL with graphics
off (`PLOP G`).

Build (Linux/macOS, needs gfortran and gcc):

    sh third_party/xfoil/build.sh      # -> third_party/xfoil/xfoil

`Dockerfile.backend` does this automatically. The server and the browser then
run the same XFOIL version and give the same results.

License: GNU General Public License (see `COPYING`).
