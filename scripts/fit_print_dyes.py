"""Fit NegPy paper dye couplings to datasheet spectral dye density curves.

Dev tool, not shipped. Turns a print medium's published dye curves into the `dye_matrix` of its
PaperProfile in negpy/features/exposure/papers.py: a density-domain coupling (rows sum to 1) in the
print kernel's `dye_mix` slot, read out as Adobe RGB like every other print.

Data (scripts/print_dyes/, 5 nm):
    kodak_ra4_e4070.csv        Kodak E-4070 Endura Premier, "Spectral-Dye-Density Curves", vector
                               paths (E-7020 Ektacolor Edge prints the same curves).
    kodak_ra4_e4021.csv        Kodak E-4021 Portra and Supra Endura (2009 issue), spektrafilm's
                               trace (CC BY-SA 4.0, see NOTICE.md).
    fujicolor_ca_af3_198e.csv  Fujifilm AF3-198E Crystal Archive bulletin, "Spectral Dye Density
                               Curves" (spectral reflection density), vector paths.
    kodak_2383_h1_2383.csv     Kodak H-1-2383 (2026 issue), "Spectral Dye Density Curves", raster,
                               traced and checked against the sheet's own visual neutral curve.
    kodak_2393_h1_2393.csv     Kodak H-1-2393t (1998), spektrafilm's trace (CC BY-SA 4.0).

Usage:
    uv run python scripts/fit_print_dyes.py [--cie-dir DIR]

The CIE 1931 2° observer and the D50/D65 tables come from files.cie.co.at, and the Kinoton 75P
xenon projector from colour-science's light-source data; all are cached in --cie-dir. The model:
an END triplet (equivalent neutral density per dye, solved so equal amounts print a visual
neutral) gives T(λ) = 10^-(Σ amount·dye(λ)), viewed under D50 for paper (the datasheets' 5000 K)
and the xenon projector for print film. Colorimetry is media-relative and Bradford-adapted to D65.
A density matrix A is fitted by Levenberg–Marquardt on CIEDE2000 between Adobe(10^-(A·END)) and
that spectral print, over near-neutral triplets and saturated one- and two-dye ramps. Densities
outside a sheet's plotted range hold its edge value.
"""

import argparse
import pathlib
import re
import urllib.request

import numpy as np

from negpy.features.exposure.papers import PAPER_PROFILES

DATA = pathlib.Path(__file__).with_name("print_dyes")
CIE_URL = "https://files.cie.co.at/Publications-datasets/"
CIE_FILES = {"cmf": "CIE_xyz_1931_2deg.csv", "D50": "CIE_std_illum_D50.csv", "D65": "CIE_std_illum_D65.csv"}
COLOUR_LIGHTS = "https://raw.githubusercontent.com/colour-science/colour/v0.4.6/colour/colorimetry/datasets/light_sources/sds.py"
WL = np.arange(380, 781, 5.0)

# key -> (csv, viewing light, paper profile that ships the fitted matrix)
MEDIA = {
    "kodak_ra4": ("kodak_ra4_e4070.csv", "D50", "kodak_endura"),
    "kodak_e4021": ("kodak_ra4_e4021.csv", "D50", "kodak_portra_endura"),
    "fuji_ra4": ("fujicolor_ca_af3_198e.csv", "D50", "fuji_crystal"),
    "kodak_2383": ("kodak_2383_h1_2383.csv", "K75P", "kodak_2383"),
    "kodak_2393": ("kodak_2393_h1_2393.csv", "K75P", "kodak_2393"),
}

ADOBE_XY = ((0.64, 0.33), (0.21, 0.71), (0.15, 0.06))
BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])


def xy_to_xyz(x, y):
    return np.array([x / y, 1.0, (1 - x - y) / y])


W65 = xy_to_xyz(0.3127, 0.3290)
P = np.stack([xy_to_xyz(*p) for p in ADOBE_XY], 1)
ADOBE_TO_XYZ = P * np.linalg.solve(P, W65)


def cie_table(cie_dir, name, cols):
    path = cie_dir / CIE_FILES[name]
    if not path.exists():
        cie_dir.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(CIE_URL + CIE_FILES[name], headers={"User-Agent": "Mozilla/5.0"})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    a = np.genfromtxt(path, delimiter=",")
    return np.stack([np.interp(WL, a[:, 0], a[:, k]) for k in range(1, cols + 1)], 1).squeeze()


def viewing_light(cie_dir, name):
    if name != "K75P":
        return cie_table(cie_dir, name, 1)
    path = cie_dir / "kinoton_75p.csv"
    if not path.exists():
        req = urllib.request.Request(COLOUR_LIGHTS, headers={"User-Agent": "Mozilla/5.0"})
        src = urllib.request.urlopen(req, timeout=60).read().decode()
        block = src[src.index('"Kinoton 75P": {') :]
        rows = re.findall(r"(\d+):\s*([0-9.eE+-]+)", block[: block.index("}")])
        cie_dir.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{w},{v}\n" for w, v in rows))
    a = np.genfromtxt(path, delimiter=",")
    return np.interp(WL, a[:, 0], a[:, 1])


def lab(xyz):
    r = xyz / W65
    f = np.where(r > (6 / 29) ** 3, np.cbrt(r), r / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def de2000(l1, l2):
    """CIEDE2000 (CIE 142-2001), kL = kC = kH = 1."""
    L1, a1, b1 = np.moveaxis(l1, -1, 0)
    L2, a2, b2 = np.moveaxis(l2, -1, 0)
    cb = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(cb**7 / (cb**7 + 25**7)))
    a1, a2 = (1 + g) * a1, (1 + g) * a2
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    h1, h2 = np.degrees(np.arctan2(b1, a1)) % 360, np.degrees(np.arctan2(b2, a2)) % 360
    dh = h2 - h1
    dh = np.where(c1 * c2 == 0, 0, np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh)))
    hs = h1 + h2
    hbar = np.where(c1 * c2 == 0, hs, np.where(np.abs(h1 - h2) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    lbar, cbar = (L1 + L2) / 2, (c1 + c2) / 2
    t = (
        1
        - 0.17 * np.cos(np.radians(hbar - 30))
        + 0.24 * np.cos(np.radians(2 * hbar))
        + 0.32 * np.cos(np.radians(3 * hbar + 6))
        - 0.20 * np.cos(np.radians(4 * hbar - 63))
    )
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbar, 1 + 0.015 * cbar * t
    rt = -2 * np.sqrt(cbar**7 / (cbar**7 + 25**7)) * np.sin(np.radians(60 * np.exp(-(((hbar - 275) / 25) ** 2))))
    dl, dc, dhh = L2 - L1, c2 - c1, 2 * np.sqrt(c1 * c2) * np.sin(np.radians(dh / 2))
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def spectral_print(csv, light, cmf):
    """END triplets -> media-relative XYZ (D65-adapted) of the datasheet dyes, and the END weights."""
    a = np.genfromtxt(DATA / csv, delimiter=",", names=True)
    dyes = np.stack([np.interp(WL, a["wavelength_nm"], a[k]) for k in ("cyan", "magenta", "yellow")], 1)
    norm = (light * cmf[:, 1]).sum()
    white = light @ cmf / norm
    adapt = np.linalg.inv(BRADFORD) @ np.diag((BRADFORD @ W65) / (BRADFORD @ (white / white[1]))) @ BRADFORD

    def xyz(amounts):
        t = 10.0 ** (-(amounts @ dyes.T))
        return ((t * light) @ cmf / norm / white[1]) @ adapt.T

    # Visual neutral of density 1.0: a* = b* = 0 and Y = 0.1 relative to the base.
    w, target = np.ones(3), lab(W65 * 0.1)[0]
    for _ in range(50):
        f0 = lab(xyz(w)) - [target, 0, 0]
        jac = np.stack([(lab(xyz(w + h)) - [target, 0, 0] - f0) / 1e-6 for h in np.eye(3) * 1e-6], 1)
        w = w - np.linalg.solve(jac, f0)
    return (lambda end: xyz(end * w)), w


def coupling(off):
    m = np.eye(3)
    for (i, j), v in zip(((0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)), off):
        m[i, j] = v
    m[np.diag_indices(3)] = 1 - (m.sum(1) - np.diag(m))
    return m


def render(end, m):
    """What the print kernel shows for these dye amounts: clipped transmittance read as Adobe RGB."""
    return lab(np.clip(10.0 ** (-(end @ m.T)), 0, 1) @ ADOBE_TO_XYZ.T)


def levenberg_marquardt(residual, x, iters=200):
    damping = 1e-3
    for _ in range(iters):
        r0 = residual(x)
        jac = np.stack([(residual(x + h) - r0) / 1e-6 for h in np.eye(len(x)) * 1e-6], 1)
        a, g = jac.T @ jac, jac.T @ r0
        while damping < 1e9:
            step = np.linalg.solve(a + damping * np.diag(np.diag(a) + 1e-12), -g)
            if (residual(x + step) ** 2).sum() < (r0**2).sum():
                x, damping = x + step, max(damping / 3, 1e-8)
                break
            damping *= 4
        else:
            break
        if np.abs(step).max() < 1e-9:
            break
    return x


def samples():
    u1, u2 = np.array([1, -1, 0]) / np.sqrt(2), np.array([1, 1, -2]) / np.sqrt(6)
    near = [[n, n, n] for n in np.linspace(0.05, 1.6, 12)]
    near += [
        n + r * (np.cos(p) * u1 + np.sin(p) * u2)
        for n in np.linspace(0.05, 1.6, 12)
        for r in (0.1, 0.2, 0.35, 0.5)
        for p in np.linspace(0, 2 * np.pi, 24, endpoint=False)
    ]
    ramps = [
        np.array(v) * d for d in np.arange(0.05, 2.001, 0.05) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1))
    ]
    return np.clip(np.array(near), 0, None), np.array(ramps)


def main():
    ap = argparse.ArgumentParser(description="Fit NegPy print dye sets to datasheet spectral dye density curves.")
    ap.add_argument("--cie-dir", type=pathlib.Path, default=pathlib.Path.home() / ".cache" / "negpy" / "cie")
    args = ap.parse_args()
    cmf = cie_table(args.cie_dir, "cmf", 3)
    near, ramps = samples()
    both = np.vstack([near, ramps])
    truths = {}
    for key, (csv, light_name, paper_key) in MEDIA.items():
        truth, weights = spectral_print(csv, viewing_light(args.cie_dir, light_name), cmf)
        truths[key] = truth
        target = lab(truth(both))
        off = levenberg_marquardt(lambda o: de2000(render(both, coupling(o)), target), np.zeros(6))
        fitted = coupling(off)
        shipped = np.array(PAPER_PROFILES[paper_key].dye_matrix, dtype=float)
        shipped /= shipped.sum(1, keepdims=True)
        print(f"\n{key}: {csv}, {light_name}, END weights {np.round(weights, 3).tolist()}")
        print("   dE00 vs the spectral print, mean / p95     near-neutral     saturated ramps")
        for name, m in (("Adobe RGB, no coupling", np.eye(3)), (f"papers.py {paper_key}", shipped), ("fitted", fitted)):
            dn = de2000(render(near, m), lab(truth(near)))
            dr = de2000(render(ramps, m), lab(truth(ramps)))
            print(f"   {name:28s} {dn.mean():5.2f} / {np.percentile(dn, 95):5.2f}    {dr.mean():5.2f} / {np.percentile(dr, 95):5.2f}")
        rows = ",\n".join(f"        ({', '.join(f'{v:.4f}' for v in r)})" for r in fitted)
        print(f"   dye_matrix=(\n{rows},\n    ),")
    keys = list(truths)
    print("\nmedium against medium, same dye amounts, near-neutral dE00 mean / p95:")
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            d = de2000(lab(truths[a](near)), lab(truths[b](near)))
            print(f"   {a} / {b}: {d.mean():.2f} / {np.percentile(d, 95):.2f}")


if __name__ == "__main__":
    main()
