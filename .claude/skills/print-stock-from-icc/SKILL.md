---
name: print-stock-from-icc
description: "Use when the user wants an ICC profile turned into a NegPy print stock (paper profile), for example a minilab, scanner or look profile such as Pakon RGBScan.icc, a Frontier or Noritsu profile, or a PaperRGB profile, or asks how closely a print stock can reproduce an ICC. Keywords: ICC, .icc, .icm, print stock, paper profile, dye matrix, dye_matrix, look, Pakon, minilab, Input ICC, fit."
---

# Print stock from ICC

A print stock can carry an ICC's colors only as a density-domain 3×3 dye matrix on Digital's curve
(`PaperProfile.dye_matrix`; rows sum to 1, so grays never move). Fit that matrix to the profile as NegPy
applies an Input ICC, measure it on real frames, and ship the nine numbers, not the profile.
*Digital (Pakon Minilab)* (`"pakon"`, fitted to `tests/fixtures/RGBScan.icc`) is the worked example.

## Does the profile qualify?

| Profile | Verdict |
|---|---|
| RGB look or minilab output space (class `spac`, `scnr` or `mntr`), made to be applied to a finished, gamma-encoded positive such as NegPy's Adobe RGB output | fit it |
| The script stops with `MOVES NEUTRALS` (the gray ramp moves over 0.5 ΔE00) | a stock keeps Digital's grays. Tell the user what moves: gray C* over 0.5 is a tint; mid-gray L* moving with C* near 0 is a tone curve, and a rise near 20 L* means the profile expects linear input |
| The script stops with `CHARACTERIZATION` (a `targ` table), the description names a target (IT8, ColorChecker), or the user made it by scanning or shooting a target | a characterization of one device: it removes that device's color and holds no look. Decline. Most scanner and camera profiles are this, with or without a `targ` table; when the source is unclear, ask the user where the profile came from |
| CMYK, or a printer/output class (`prtr`) | not a look; decline |
| Modelled from datasheet dyes (spektrafilm, PaperRGB LUTs) | do not ship it or a matrix fitted to it (see the data rule below) |
| The script's closest shipped dyes are under about 0.3 ΔE00 | it adds no new color; see "Duplicate" below |

**After a decline**, say where the profile belongs instead. A characterization goes in Export › Input ICC for raw
scans from that device. A profile that moves grays can only be applied whole, as Input ICC with Soft Proof. A
duplicate is served by the existing stock's matrix on Digital's curve.

**Data rule.** NegPy ships color data from manufacturer datasheets, standards, papers, or the profile of
a real machine (a minilab's or scanner's own LUT, such as RGBScan.icc). A profile modelled from datasheet
dyes is model output: it adds a second source for data NegPy already fits from the sheet itself.

**Duplicate.** The closest-dyes line compares two matrices on the grid, which is the right measure for
that question. Confirm on real frames with `--stock <that key>`: if the shipped matrix lands within about
0.1 ΔE00 of the fit, offer it instead. Move it to a shared constant (like `_ENDURA_DYE`), add a stock on
Digital's curve that uses it, and add no fixture and no `ICC_STOCKS` entry, because the data comes from the sheet.

## Steps

1. **Fit:** `uv run python scripts/fit_icc_dyes.py PATH.icc`, from the repo root, with the profile kept outside the repo. It prints the profile header and stops on a decline it can detect. Otherwise it prints the path NegPy uses for it (primaries only for a matrix/TRC profile, full CMS for a LUT), the neutral check, the grid residual against Digital, the `dye_matrix=(...)` block and the closest shipped dyes. Check the table above before going on.
2. **Measure on real frames.** Get 3 to 6 color negatives rendered on the Digital stock as TIFF in Adobe RGB, with no Input ICC and Paper White off: a NegPy export, or `base_positive` from the `verify` skill's headless driver saved as 16-bit TIFF. Run `uv run python scripts/fit_icc_dyes.py PATH.icc --images A.tif B.tif ...`, adding `--stock KEY` once the stock exists. If you have no frames, ask the user for exports. Grid numbers are not a real-frame result.
3. **Report**, for the stock and for plain Digital, each against the profile: mean, p95, and the share of pixels over 1, 2 and 3 ΔE00. Read them with the table below. For the ceiling, quote the script's hue table (chroma kept by the profile and by the stock) and its share of misses in dark pixels.
4. **Ship** (next section). Run the targeted checks, not the full pipeline: `uv run pytest tests/test_paper_profiles.py` and `uv run ruff check` on the changed files. Then the `verify` skill: pick the stock on a real frame in the app and check that it renders.

## Reading the numbers

| ΔE00 | What a viewer sees |
|---|---|
| under 1 | nothing, even on flat patches side by side |
| 1 to 2 | a trained eye, on flat patches side by side; rarely in a photo |
| 2 to 3 | visible side by side |
| 3 and over | visible at a glance side by side |

Photographs tolerate more than flat patches. For reference, Pakon on six scans: stock 0.85 mean, 6.7 % of
pixels over 2, 1.2 % over 3; Digital 1.72, 34 % and 21 %.

**Ceiling.** A 3×3 scales opposite hues alike, so a profile that mutes one hue and keeps its opposite
(Pakon: orange ×0.77, sky ×0.97) lands between the two. A hue turn that grows in deep, saturated shadows
also stays. On Pakon a nonlinear kernel term gained at most 0.13; a 3D LUT is exact but needs a new CPU
and GPU stage. Report these; build neither unless the user asks.

## Ship

- `negpy/features/exposure/papers.py`: a `PaperProfile` with `kind="ra4"` (the Color Negative list; dict order is menu order), the user's label, no tonal keys, the printed `dye_matrix`, and a one-line comment naming the profile and `scripts/fit_icc_dyes.py`. Never `kind="default"`.
- Tests: the rows-sum and chromatic-ramp tests in `tests/test_paper_profiles.py` cover the entry. If the profile may be redistributed and the data-source rule allows it, copy it to `tests/fixtures/` and add one entry to `ICC_STOCKS` there.
- Docs: one phrase in the Print stock bullet of `docs/USER_GUIDE.md` and in the paper combo's tooltip (`sidebar/paper.py`); add the stock to the bundled list under "Print stocks" in `docs/PIPELINE.md`.
- No `THUMBNAIL_RENDER_VERSION` bump and no migration: a new stock changes no existing render.
- Credit the profile's source in `NOTICE.md` when its license asks for attribution.

## Common mistakes

| Mistake | Fix |
|---|---|
| Building the target with another rendering intent, or without BPC | The script applies the profile as NegPy does: lcms at 16 bit, relative colorimetric with BPC, or primaries only for a matrix/TRC profile |
| Running the script with `python -I` | It drops `scripts/` from the import path. The profile is read as data, so run the command as written from the repo root |
| Treating the encoded output as linear | Adobe RGB's TRC is a pure 563/256 power |
| Replaying the matrix without black point compensation | The kernel maps Digital's d_max 2.3 to black; the script does the same |
| Fitting a linear-RGB 3×3 | The stock slot is density; fit through it |
| Calling the grid residual the result | The grid over-weights saturated colors; measure real frames |
