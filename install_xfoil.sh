#!/bin/bash
set -e 

echo "Starting XFOIL Installation (HEADLESS MODE)..."

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

echo "Creating dummy plotlib (no graphics)..."
cd "$PLOTLIB_DIR"

# Create minimal dummy plot library with all required functions
cat > dummy_plot.f <<'EOF'
      SUBROUTINE PLTINI
      RETURN
      END

      SUBROUTINE PLOT(X,Y,IPEN)
      REAL X,Y
      INTEGER IPEN
      RETURN
      END
      
      SUBROUTINE NEWPEN(IPEN)
      INTEGER IPEN
      RETURN
      END
      
      SUBROUTINE PLFLSH
      RETURN
      END
      
      SUBROUTINE PLSYMB(X,Y,SH,CH,A,NC)
      REAL X,Y,SH,A
      INTEGER NC
      CHARACTER*(*) CH
      RETURN
      END
      
      SUBROUTINE PLCHAR(X,Y,SH,CH,A,NC)
      REAL X,Y,SH,A
      INTEGER NC
      CHARACTER*(*) CH  
      RETURN
      END
      
      SUBROUTINE PLNUMB(X,Y,SH,R,A,ND)
      REAL X,Y,SH,R,A
      INTEGER ND
      RETURN
      END
      
      SUBROUTINE GETCOLOR(ICOL)
      INTEGER ICOL
      ICOL = 1
      RETURN
      END
      
      SUBROUTINE NEWCOLORNAME(CNAME)
      CHARACTER*(*) CNAME
      RETURN  
      END
      
      SUBROUTINE NEWCOLOR(ICOL)
      INTEGER ICOL
      RETURN
      END
      
      SUBROUTINE GETCOLORRGB(ICOL,R,G,B)
      INTEGER ICOL
      REAL R,G,B
      R = 1.0
      G = 1.0  
      B = 1.0
      RETURN
      END
      
      SUBROUTINE PLGRID(X1,X2,DX,Y1,Y2,DY)
      REAL X1,X2,DX,Y1,Y2,DY
      RETURN
      END
      
      SUBROUTINE NEWPAT(IPAT)
      INTEGER IPAT
      RETURN
      END
      
      SUBROUTINE PLOTABS(X,Y,IPEN)
      REAL X,Y
      INTEGER IPEN
      RETURN
      END
EOF

# Compile dummy plotlib
echo "Compiling dummy plotlib..."
gfortran -c -fallow-argument-mismatch dummy_plot.f -o dummy_plot.o
ar cr libPlt.a dummy_plot.o
ranlib libPlt.a

# Create symbolic links that XFOIL expects
ln -sf libPlt.a libPlt_gSP.a
ln -sf libPlt.a libPlt_gDP.a

echo "✅ Dummy plotlib created"

# Now compile XFOIL binary
if [ -n "$BIN_DIR" ]; then
    cd "$BIN_DIR"
    
    echo "Patching XFOIL Makefile..."
    
    # Update compiler settings
    sed -i 's/FC = f77/FC = gfortran/g' Makefile
    sed -i 's/CC = cc/CC = gcc/g' Makefile
    sed -i 's/FFLAGS = /FFLAGS = -fallow-argument-mismatch /g' Makefile
    
    # Remove ALL X11 library references completely
    sed -i 's/-lX11//g' Makefile
    sed -i 's/-lXext//g' Makefile
    sed -i 's/-L \/usr\/X11R6\/lib//g' Makefile
    sed -i 's/-L\/usr\/X11R6\/lib//g' Makefile
    sed -i 's/-L \/usr\/lib\/x86_64-linux-gnu//g' Makefile
    sed -i 's/-L\/usr\/lib\/x86_64-linux-gnu//g' Makefile
    sed -i 's/-L  / /g' Makefile
    sed -i 's/-L / /g' Makefile
    
    # Point to our dummy plotlib
    sed -i 's|PLTOBJ = .*|PLTOBJ = ../plotlib/libPlt.a|g' Makefile
    
    echo "Building XFOIL (headless)..."
    make xfoil
    
    # Install
    if [ -f "xfoil" ]; then
        cp xfoil /usr/local/bin/
        chmod +x /usr/local/bin/xfoil
        echo "🎉 XFOIL INSTALLED SUCCESSFULLY (HEADLESS MODE)"
    else
        echo "❌ XFOIL binary not created"
        ls -la
        exit 1
    fi
else
    echo "❌ BIN directory not found"
    exit 1
fi