---
title: 'AeroLab: A Web-Based Airfoil Aerodynamic Analysis Tool with Robust Coordinate Parsing and Interactive Flow Visualisation'
tags:
  - Python
  - aerodynamics
  - airfoil
  - XFOIL
  - panel method
  - lattice-boltzmann
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

AeroLab is a free, browser-based aerodynamic analysis tool that wraps the XFOIL panel method solver [@Drela1989] in an accessible web interface. Users supply an airfoil coordinate file, a Reynolds number, and an angle of attack; AeroLab returns lift coefficient (C~L~), drag coefficient (C~D~), pitching moment coefficient (C~m~), pressure distribution (C~p~), and an interactive flow visualisation — all without installing any software.

The tool makes two contributions beyond simply wrapping XFOIL. First, it implements a robust coordinate parser that automatically resolves the formatting inconsistencies common in publicly available airfoil databases, which stock XFOIL rejects without user intervention. Second, it integrates an interactive GPU-accelerated D2Q9 Lattice-Boltzmann wind tunnel that visualises flow around the user's actual uploaded airfoil geometry in real time — combining coordinate repair, viscous analysis, and unsteady flow visualisation in a single browser-based workflow requiring no installation.

# Statement of Need

XFOIL [@Drela1989] is the most widely used low Reynolds number airfoil analysis code in aerospace education and research. However, its command-line interface and strict coordinate file requirements create significant friction for new users. Two problems are particularly common in practice:

**Coordinate file incompatibility.** Airfoil databases such as the UIUC Airfoil Coordinate Database [@Selig1996] and Airfoil Tools distribute coordinates in multiple formats — primarily Selig format (a single contiguous loop from trailing edge, over the upper surface, to the leading edge, and back along the lower surface) and Lednicer format (two separate upper and lower surface sections). Files frequently contain additional issues including incorrect winding order, duplicate leading or trailing edge points, mixed whitespace delimiters, and header lines. Stock XFOIL silently produces incorrect results or crashes entirely when given malformed input, requiring users to manually inspect and correct files before analysis.

**Lack of flow visualisation.** XFOIL outputs tabular coefficient and pressure data but provides no visual representation of the flow field. Understanding the relationship between airfoil geometry, angle of attack, and the surrounding velocity field — including the acceleration over the suction surface, boundary layer separation, and wake structure — is central to aerodynamics education, yet requires additional software to visualise.

Existing web-based XFOIL interfaces address the accessibility barrier but do not resolve either of these issues. AeroLab addresses both.

# State of the Field

Several tools exist for airfoil aerodynamic analysis, ranging from desktop applications to online interfaces. XFOIL [@Drela1989] itself remains the dominant solver for low Reynolds number analysis but requires local installation and manual coordinate file preparation. XFLR5 provides a graphical interface to XFOIL and extends it to three-dimensional wing analysis, but is a desktop application requiring installation. Web-based wrappers for XFOIL exist (e.g., Airfoil Tools) but do not implement robust coordinate preprocessing, meaning users must still manually resolve file format issues before analysis. Interactive LBM flow visualisers such as Kutta [@Gimenes2026] exist as standalone tools but are not integrated with coordinate preprocessing pipelines or XFOIL analysis workflows, and operate only on parametric airfoil shapes rather than arbitrary user-supplied geometry. AeroLab addresses these gaps by combining automatic coordinate repair, XFOIL-powered viscous analysis, and an interactive GPU-accelerated LBM wind tunnel operating on the user's actual uploaded airfoil geometry — all in a single browser-based tool requiring no installation.

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

## Interactive Wind Tunnel

An interactive flow visualisation is implemented as a WebGL2 component (`airfoil_flow_lbm_aerolab.html`) embedded in the Streamlit frontend via `st.components.v1.html()`. The solver uses the D2Q9 Lattice-Boltzmann Method (LBM) with single-relaxation BGK collision, running entirely on the GPU via GLSL fragment shaders. The user's parsed airfoil coordinates are serialised as a JSON array by the Python backend and injected into the JavaScript component at render time, where they are rasterised onto the LBM grid as a no-slip solid mask using the half-way bounce-back boundary condition. This pipeline means the same coordinate file that the parser repairs and XFOIL analyses is immediately visualised in the interactive wind tunnel — no separate geometry input is required.

The component provides real-time interactive controls: an angle of attack slider (−20° to +25°) that pitches the airfoil geometry while keeping the freestream horizontal, a flow speed slider, and a particle trail density slider. Three field visualisation modes are available — velocity magnitude, pressure coefficient, and vorticity (out-of-plane curl) — rendered as a colour field updated every frame by the GPU. Passive smoke tracer particles are advected through the velocity field using bilinear interpolation, producing streakline visualisations analogous to smoke-wire experiments. A surface separation fraction is computed each frame by counting fluid cells adjacent to the solid body where the streamwise velocity is reversed, providing a qualitative stall indicator. Numerical stability is maintained through macroscopic field clamping (ρ ∈ [0.5, 2.0], |u| ≤ 0.35 U~0~).

# Research Impact Statement

AeroLab lowers the barrier to entry for airfoil aerodynamic analysis by eliminating the two most common friction points for new users: coordinate file incompatibility and the absence of flow visualisation. The parser has been validated against 1,000 airfoil files from the UIUC database, with full benchmark methodology and results reported separately [@Pranav2026benchmark]. The tool is freely accessible at https://aerolab-app.onrender.com and is intended for use in aerodynamics education and early-stage research, particularly for users without access to commercial CFD software.

# AI Usage Disclosure

Generative AI was used as a coding assistant during the development of AeroLab, including troubleshooting and test scaffolding. AI assistance was also used for copy-editing during preparation of this manuscript. All AI-assisted outputs were reviewed, validated, and modified by the author. Core design decisions, problem framing, and architectural choices were made by the human author. The author takes full responsibility for all submitted materials.

# Acknowledgements

AeroLab is built on XFOIL, developed by Professor Mark Drela at MIT. The interactive wind tunnel component builds on the D2Q9 LBM approach demonstrated in the Kutta open-source flow visualiser [@Gimenes]. The author thanks the maintainers of the UIUC Airfoil Coordinate Database for providing the reference airfoil data used in testing.

# References
