"""
test_main.py — Unit tests for AeroLab backend (main.py)

Tests cover:
  - parse_dat_file: coordinate parsing and validation
  - detect_and_merge_sections: Selig vs Lednicer format handling,
    winding order correction, duplicate point removal
  - extract_aerodynamic_coefficients: regex extraction from XFOIL stdout

Run with:  pytest test_main.py -v
"""

import os
import tempfile
import pytest

from main import (
    parse_dat_file,
    detect_and_merge_sections,
    extract_aerodynamic_coefficients,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def write_dat(tmp_path, lines):
    """Write lines to a temporary .dat file and return its path."""
    p = tmp_path / "test.dat"
    p.write_text("\n".join(lines))
    return str(p)


def naca0012_selig():
    """Minimal NACA 0012 in Selig format (TE → upper → LE → lower → TE)."""
    return [
        "NACA 0012",
        "1.000000  0.001260",
        "0.933013  0.005740",
        "0.750000  0.015970",
        "0.500000  0.030230",
        "0.250000  0.041210",
        "0.066987  0.031530",
        "0.000000  0.000000",
        "0.066987 -0.031530",
        "0.250000 -0.041210",
        "0.500000 -0.030230",
        "0.750000 -0.015970",
        "0.933013 -0.005740",
        "1.000000 -0.001260",
    ]


# ── parse_dat_file ─────────────────────────────────────────────────────────

class TestParseDatFile:

    def test_parses_valid_selig(self, tmp_path):
        path = write_dat(tmp_path, naca0012_selig())
        coords = parse_dat_file(path)
        assert len(coords) >= 10
        xs = [pt[0] for pt in coords]
        assert all(0.0 <= x <= 1.0 for x in xs), "All x coords should be in [0, 1]"

    def test_skips_header_line(self, tmp_path):
        lines = ["NACA 0012"] + [f"{x:.4f}  {y:.4f}"
                                  for x, y in zip([1, 0.75, 0.5, 0.25, 0, 0.25, 0.5, 0.75, 1, 0.5],
                                                  [0, 0.01, 0.02, 0.03, 0, -0.03, -0.02, -0.01, 0, 0])]
        path = write_dat(tmp_path, lines)
        coords = parse_dat_file(path)
        # Header should be silently skipped
        assert all(isinstance(pt[0], float) for pt in coords)

    def test_skips_blank_lines(self, tmp_path):
        lines = naca0012_selig()
        lines_with_blanks = lines[:5] + ["", "  "] + lines[5:]
        path = write_dat(tmp_path, lines_with_blanks)
        coords = parse_dat_file(path)
        assert len(coords) >= 10

    def test_rejects_out_of_range_coords(self, tmp_path):
        # All points outside valid x range — should raise HTTPException
        from fastapi import HTTPException
        lines = ["2.0  0.5", "3.0  0.1", "-2.0  0.0"]
        path = write_dat(tmp_path, lines)
        with pytest.raises(HTTPException):
            parse_dat_file(path)

    def test_rejects_too_few_points(self, tmp_path):
        from fastapi import HTTPException
        lines = ["0.5  0.01", "0.3  0.02"]   # only 2 points
        path = write_dat(tmp_path, lines)
        with pytest.raises(HTTPException):
            parse_dat_file(path)

    def test_handles_tab_separated(self, tmp_path):
        lines = ["NACA 0012"] + [f"{x:.4f}\t{y:.4f}"
                                  for x, y in zip(
                                      [1, 0.75, 0.5, 0.25, 0, 0.25, 0.5, 0.75, 1, 0.5, 0.3],
                                      [0, 0.01, 0.02, 0.03, 0, -0.03, -0.02, -0.01, 0, 0, 0])]
        path = write_dat(tmp_path, lines)
        coords = parse_dat_file(path)
        assert len(coords) >= 10

    def test_file_not_found_raises(self):
        from fastapi import HTTPException
        with pytest.raises((HTTPException, FileNotFoundError, Exception)):
            parse_dat_file("/nonexistent/path/file.dat")


# ── detect_and_merge_sections ──────────────────────────────────────────────

class TestDetectAndMergeSections:

    def test_selig_single_section_passthrough(self):
        """Selig format: single continuous loop, should pass through unchanged."""
        data = [
            [1.0, 0.001], [0.75, 0.016], [0.5, 0.030], [0.25, 0.041],
            [0.0, 0.0],
            [0.25, -0.041], [0.5, -0.030], [0.75, -0.016], [1.0, -0.001],
        ]
        result = detect_and_merge_sections(data)
        assert len(result) >= 8

    def test_lednicer_format_detected(self):
        """Lednicer format: two separate sections (upper and lower), each LE→TE."""
        upper = [[0.0, 0.0], [0.25, 0.041], [0.5, 0.030], [0.75, 0.016], [1.0, 0.001]]
        lower = [[0.0, 0.0], [0.25, -0.041], [0.5, -0.030], [0.75, -0.016], [1.0, -0.001]]
        data = upper + lower
        result = detect_and_merge_sections(data)
        # Result should be a single merged list
        assert isinstance(result, list)
        assert len(result) > 0

    def test_naca6series_closed_te_regression(self):
        """Regression test for the NACA 6-series bug: these files are a closed
        Selig loop whose first and last point are both exactly (1.0, 0.0).
        The parser must keep every point so the trailing edge stays closed."""
        # Abbreviated NACA 65-210-style loop: TE -> upper -> LE -> lower -> TE
        data = [
            [1.00000, 0.00000],
            [0.50000, 0.05915],
            [0.10000, 0.03555],
            [0.00435, 0.00819],
            [0.00000, 0.00000],
            [0.00565, -0.00719],
            [0.10000, -0.02521],
            [0.50000, -0.03709],
            [1.00000, 0.00000],
        ]
        n_before = len(data)
        result = detect_and_merge_sections(data)
        assert len(result) == n_before, "No point should be dropped"
        assert result[-1][0] == 1.0 and abs(result[-1][1]) < 1e-6, \
            "Final trailing-edge point must be preserved"

    def test_preserves_closed_trailing_edge(self):
        """A Selig airfoil that starts and ends at the same TE point is a
        valid closed loop (common in NACA 6-series). The closing point must
        be PRESERVED — removing it opens the trailing edge and breaks XFOIL
        convergence."""
        data = [
            [1.0, 0.0], [0.75, 0.016], [0.5, 0.030], [0.25, 0.041],
            [0.0, 0.0],
            [0.25, -0.041], [0.5, -0.030], [0.75, -0.016], [1.0, 0.0],
        ]
        n_before = len(data)
        result = detect_and_merge_sections(data)
        # The closing TE point should still be there — no point dropped.
        assert len(result) == n_before, \
            "Closed trailing edge point was incorrectly removed"
        # And the loop should remain closed (first == last).
        assert (abs(result[0][0] - result[-1][0]) < 0.001 and
                abs(result[0][1] - result[-1][1]) < 0.001), \
            "Trailing edge should remain closed"

    def test_reversed_selig_corrected(self):
        """Reversed Selig (TE→lower→LE→upper→TE) should be flipped."""
        # Wrong winding: TE → lower → LE → upper → TE
        data_reversed = [
            [1.0, -0.001], [0.75, -0.016], [0.5, -0.030], [0.25, -0.041],
            [0.0, 0.0],
            [0.25, 0.041], [0.5, 0.030], [0.75, 0.016], [1.0, 0.001],
        ]
        result = detect_and_merge_sections(data_reversed)
        # After correction the point just before LE (x≈0) should have positive y
        le_idx = min(range(len(result)), key=lambda i: result[i][0])
        if le_idx > 0:
            assert result[le_idx - 1][1] >= 0, \
                "Winding order correction failed: point before LE should be on upper surface"

    def test_lednicer_removes_duplicate_le(self):
        """Lednicer lower section often duplicates the LE point — it should be removed."""
        upper = [[0.0, 0.0], [0.25, 0.041], [0.5, 0.030], [0.75, 0.016], [1.0, 0.001]]
        lower = [[0.0, 0.0], [0.25, -0.041], [0.5, -0.030], [0.75, -0.016], [1.0, -0.001]]
        data = upper + lower
        result = detect_and_merge_sections(data)
        # Count how many times (0, 0) appears — should be at most 1
        le_count = sum(1 for pt in result if abs(pt[0]) < 0.001 and abs(pt[1]) < 0.001)
        assert le_count <= 1, f"Duplicate LE not removed: found {le_count} LE points"


# ── extract_aerodynamic_coefficients ──────────────────────────────────────

class TestExtractAerodynamicCoefficients:

    # Realistic snippet of XFOIL stdout
    XFOIL_STDOUT = """
 Solving BL system ...
  a =  5.000   CL =  0.6352   CD = 0.009241   CDp = 0.007812   Cm = -0.0521
 VISCAL:  Convergence achieved in 12 iterations
    """

    def test_extracts_cl(self):
        coeffs = extract_aerodynamic_coefficients(self.XFOIL_STDOUT)
        assert "CL" in coeffs
        assert abs(coeffs["CL"] - 0.6352) < 1e-4

    def test_extracts_cd(self):
        coeffs = extract_aerodynamic_coefficients(self.XFOIL_STDOUT)
        assert "CD" in coeffs
        assert abs(coeffs["CD"] - 0.009241) < 1e-6

    def test_extracts_cdp(self):
        coeffs = extract_aerodynamic_coefficients(self.XFOIL_STDOUT)
        assert "CDp" in coeffs
        assert abs(coeffs["CDp"] - 0.007812) < 1e-6

    def test_extracts_cm(self):
        coeffs = extract_aerodynamic_coefficients(self.XFOIL_STDOUT)
        assert "Cm" in coeffs
        assert abs(coeffs["Cm"] - (-0.0521)) < 1e-4

    def test_takes_last_occurrence(self):
        """If XFOIL iterates and prints multiple CL values, the last one should be used."""
        stdout = """
  a =  5.000   CL =  0.5000   CD = 0.010000   CDp = 0.008000   Cm = -0.050
  a =  5.000   CL =  0.6352   CD = 0.009241   CDp = 0.007812   Cm = -0.0521
        """
        coeffs = extract_aerodynamic_coefficients(stdout)
        assert abs(coeffs["CL"] - 0.6352) < 1e-4, \
            "Should use last (converged) CL value, not first"

    def test_returns_empty_dict_on_no_match(self):
        coeffs = extract_aerodynamic_coefficients("XFOIL  Version 6.99\n\n")
        assert coeffs == {}

    def test_handles_negative_cl(self):
        stdout = "  CL = -0.3214   CD = 0.011200   CDp = 0.009100   Cm =  0.0312"
        coeffs = extract_aerodynamic_coefficients(stdout)
        assert coeffs["CL"] < 0

    def test_handles_zero_alpha(self):
        stdout = "  CL =  0.0000   CD = 0.006500   CDp = 0.005200   Cm =  0.0000"
        coeffs = extract_aerodynamic_coefficients(stdout)
        assert abs(coeffs["CL"]) < 1e-4