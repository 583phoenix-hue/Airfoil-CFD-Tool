---
title: 'AeroLab: A Web-Based Airfoil Aerodynamic Analysis Tool with Robust Coordinate Parsing and Potential Flow Visualisation'
tags:
  - Python
  - aerodynamics
  - airfoil
  - XFOIL
  - panel method
  - computational fluid dynamics
  - education
authors:
  - name: Nathan Pranav
    orcid: 0009-0005-4120-635X
    affiliation: 1
affiliations:
  - name: Independent Researcher
    index: 1
date: 2026
bibliography: paper.bib
---

# Summary

AeroLab is a free, browser-based aerodynamic analysis tool that wraps the XFOIL panel method solver [@Drela1989] in an accessible web interface. Users supply an airfoil coordinate file, a Reynolds number, and an angle of attack; AeroLab returns lift coefficient (C~L~), drag coefficient (C~D~), pitching moment coefficient (C~m~), pressure distribution (C~p~), and an animated potential flow visualisation — all without installing any software.

The tool makes two novel contributions beyond simply wrapping XFOIL. First, it implements a robust coordinate parser that automatically resolves the formatting inconsistencies common in publicly available airfoil databases, which stock XFOIL rejects without user intervention. Second, it provides an independent 160-panel vortex panel method implementation for off-body flow field computation and animated visualisation, augmented with boundary layer displacement thickness and laminar-to-turbulent transition data extracted from XFOIL's viscous solution.

# Statement of Need

XFOIL [@Drela1989] is the most widely used low Reynolds number airfoil analysis code in aerospace education and research. However, its command-line interface and strict coordinate file requirements create significant friction for new users. Two problems are particularly common in practice:

**Coordinate file incompatibility.** Airfoil databases such as the UIUC Airfoil Coordinate Database [@Selig1996] and Airfoil Tools distribute coordinates in multiple formats — primarily Selig format (a single contiguous loop from trailing edge, over the upper surface, to the leading edge, and back along the lower surface) and Lednicer format (two separate upper and lower surface sections). Files frequently contain additional issues including incorrect winding order, duplicate leading or trailing edge points, mixed whitespace delimiters, and header lines. Stock XFOIL silently produces incorrect results or crashes entirely when given malformed input, requiring users to manually inspect and correct files before analysis.

**Lack of flow visualisation.** XFOIL outputs tabular coefficient and pressure data but provides no visual representation of the flow field. Understanding the relationship between airfoil geometry, angle of attack, and the surrounding velocity field — including the acceleration over the suction surface and the structure of the boundary layer — is central to aerodynamics education, yet requires additional software to visualise.

Existing web-based XFOIL interfaces address the accessibility barrier but do not resolve either of these issues. AeroLab addresses both.

# State of the Field

Several tools exist for airfoil aerodynamic analysis, ranging from desktop applications to online interfaces. XFOIL [@Drela1989] itself remains the dominant solver for low Reynolds number analysis but requires local installation and manual coordinate file preparation. XFLR5 provides a graphical interface to XFOIL and extends it to three-dimensional wing analysis, but is a desktop application requiring installation. Web-based wrappers for XFOIL exist (e.g., Airfoil Tools) but do not implement robust coordinate preprocessing, meaning users must still manually resolve file format issues before analysis. None of the existing web-based tools provide animated potential flow visualisation as a built-in feature. AeroLab addresses these gaps by combining automatic coordinate repair, XFOIL-powered viscous analysis, and independent potential flow visualisation in a single browser-based tool requiring no installation.

# Software Design

## Coordinate Parser

The parser (`parse_dat_file`, `detect_and_merge_sections` in `main.py`) reads coordinate files and applies the following corrections in sequence:

1. **Format detection** — identifies Selig (single section) versus Lednicer (two sections separated by a return to near-zero x) format by scanning for a section break where x drops below 0.01 after exceeding 0.5.
2. **Winding order correction** — for Selig files, determines correct winding direction by inspecting the y-coordinate of the point immediately preceding the leading edge; a negative value indicates reversed winding and the coordinate list is reversed.
3. **Duplicate point removal** — removes duplicate leading edge points that appear when Lednicer lower sections repeat the (0, 0) origin, and preserves closed trailing edge points where the first and last coordinates coincide (required for correct XFOIL panelling of NACA 6-series laminar airfoils).
4. **Range filtering** — discards points outside physically plausible bounds (x ∈ [−0.5, 1.5], y ∈ [−1.0, 1.0]) and rejects files with fewer than ten valid coordinate pairs.

## XFOIL Integration

The backend (`main.py`) exposes a FastAPI endpoint that accepts a coordinate file, Reynolds number, and angle of attack. XFOIL is invoked as a subprocess via a generated command script. A three-strategy retry scheme maximises convergence rate: viscous mode with clean geometry is attempted first, followed by viscous mode with XFOIL geometry smoothing (`GDES SMOO`), and finally inviscid mode as a fallback. Concurrent requests are managed via an asyncio semaphore (limit: 3 simultaneous XFOIL processes). Rate limiting is applied at the API level via SlowAPI.

Boundary layer data is extracted from XFOIL's `DUMP` output, which provides arc length, surface coordinates, edge velocity ratio (U~e~/V~∞~), displacement thickness (δ*), momentum thickness (θ), skin friction coefficient (C~f~), and shape factor (H) for upper and lower surfaces. Laminar-to-turbulent transition locations are detected from sharp increases in C~f~ along each surface.

## Potential Flow Visualisation

An independent vortex panel method is implemented in `Airfoil_Analysis.py` (`compute_flow_field`) for flow field visualisation. The method uses N = 160 constant-strength vortex panels with cosine arc-length spacing. The influence matrix is assembled using the standard vortex panel velocity kernel [@Katz2001], with the Kutta condition enforced by replacing the final matrix row with the constraint γ~1~ + γ~N~ = 0. For airfoils where cosine spacing produces an ill-conditioned system (detected by max|γ| > 500), the solver automatically retries with uniform arc-length spacing.

The off-body velocity field is computed on a 220 × 220 grid by superimposing the freestream and the vortex panel contributions at each grid point. Interior grid points are masked using matplotlib's `Path.contains_points`. Streamlines are integrated from left-boundary seed points using a first-order Euler scheme with bilinear velocity interpolation. The resulting animation is rendered in Plotly with a matplotlib-generated bicubic-interpolated speed heatmap as a static background layer, enabling smooth colour transitions without per-frame re-rendering.

# Research Impact Statement

AeroLab lowers the barrier to entry for airfoil aerodynamic analysis by eliminating the two most common friction points for new users: coordinate file incompatibility and the absence of flow visualisation. A benchmark study across 1,000 airfoil coordinate files from the UIUC Airfoil Coordinate Database demonstrates that AeroLab's coordinate parser increases XFOIL analysis success rates from 22.5% (raw XFOIL) to 85.7%, rescuing 633 files through automatic format detection and repair [@Pranav2026benchmark]. The tool is freely accessible at https://aerolab.me and is intended for use in aerodynamics education and early-stage research, particularly for users without access to commercial CFD software.

# AI Usage Disclosure

Generative AI was used as a coding assistant during the development of AeroLab, such as troubleshooting and test scaffolding. AI assistance was also used for copy-editing during preparation of this manuscript. All AI-assisted outputs were reviewed, validated, and modified by the author. Core design decisions, problem framing, and architectural choices were made by the human author. The author takes full responsibility for all submitted materials.

# Acknowledgements

AeroLab is built on XFOIL, developed by Professor Mark Drela at MIT. The author thanks the maintainers of the UIUC Airfoil Coordinate Database for providing the reference airfoil data used in testing.

# References