"""Fit a print stock's dye coupling to an RGB profile applied to NegPy's Adobe RGB output.

Dev tool, not shipped. A print stock carries an ICC's colors as a density 3x3 on Digital's curve
(`PaperProfile.dye_matrix`, rows sum to 1, so grays stay put). The target is the profile applied as
NegPy applies an Input ICC: a matrix/TRC profile by its primaries alone, in linear light, any other
through lcms at 16 bit, relative colorimetric with black point compensation. A profile that moves grays
or carries a targ measurement table (a device characterization) stops the run before the fit. The fit is Levenberg–Marquardt on CIEDE2000 over an L*C*h grid inside
Adobe RGB, through the print kernel's dye mix and black point compensation. The Digital (Pakon Minilab)
stock is this fit of tests/fixtures/RGBScan.icc ("Pakon spac unblended toe g22", public domain).

Usage:
    uv run python scripts/fit_icc_dyes.py [ICC] [--stock KEY] [--images TIFF ...]

--stock compares a shipped stock's matrix. --images measures real frames: each a NegPy export on the
Digital stock (TIFF, Adobe RGB, no Input ICC, Paper White off) against the profile applied to it. The
closest shipped dyes are listed because a profile modelled on datasheet dyes NegPy already fits adds no
new color.
"""

import argparse
import pathlib
import struct

import imagecodecs
import numpy as np
from fit_print_dyes import ADOBE_TO_XYZ, W65, coupling, de2000, lab, levenberg_marquardt

from negpy.features.exposure.models import EXPOSURE_CONSTANTS
from negpy.features.exposure.papers import PAPER_PROFILES, resolve_dye_matrix
from negpy.infrastructure.display.color_spaces import WORKING_COLOR_SPACE, ColorSpaceRegistry
from negpy.infrastructure.display.icc_profile import extract_primaries_matrix, is_matrix_trc_profile
from negpy.kernel.image.logic import apply_primaries_transform

REPO = pathlib.Path(__file__).resolve().parents[1]
GAMMA = 563 / 256
BLACK = 10.0 ** -EXPOSURE_CONSTANTS["d_max"]
# A stock cannot move grays, so a profile that moves them past this is not a dye look.
NEUTRAL_LIMIT = 0.5


def header(icc):
    """Device class, color space, connection space, creator, description, and whether it carries a targ table."""
    cls, space, pcs, creator = (icc[a : a + 4].decode("latin-1").strip("\x00 ") for a in (12, 16, 20, 80))
    desc, targ = "", False
    for i in range(struct.unpack(">I", icc[128:132])[0]):
        sig, off, size = struct.unpack(">4sII", icc[132 + 12 * i : 144 + 12 * i])
        targ |= sig == b"targ"
        if sig != b"desc":
            continue
        if icc[off : off + 4] == b"mluc":  # v4: UTF-16BE records; take the first
            length, start = struct.unpack(">II", icc[off + 20 : off + 28])
            desc = icc[off + start : off + start + length].decode("utf-16-be", "replace")
        else:
            desc = icc[off + 12 : off + size].split(b"\x00")[0].decode("latin-1", "replace")
    return cls, space, pcs, creator, desc.strip(), targ


def lab_to_adobe(L):
    fy = (L[..., 0] + 16) / 116
    f = np.stack([fy + L[..., 1] / 500, fy, fy - L[..., 2] / 200], -1)
    xyz = np.where(f > 6 / 29, f**3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * W65
    return xyz @ np.linalg.inv(ADOBE_TO_XYZ).T


def grid():
    """Linear Adobe RGB colors on an L*C*h grid, the ones inside the gamut."""
    L, h, c = np.meshgrid(np.arange(20, 91, 10.0), np.radians(np.arange(0, 360, 15.0)), (5, 10, 20, 30, 45, 60, 80.0))
    rgb = lab_to_adobe(np.stack([L, c * np.cos(h), c * np.sin(h)], -1).reshape(-1, 3))
    return rgb[((rgb >= 0) & (rgb <= 1)).all(1)]


def profile_on_adobe(rgb, icc):
    enc = np.clip(rgb, 0, 1) ** (1 / GAMMA)
    src_to_xyz = extract_primaries_matrix(icc) if is_matrix_trc_profile(icc) else None
    if src_to_xyz is not None:
        out = apply_primaries_transform(enc.reshape(-1, 1, 3).astype(np.float32), src_to_xyz)
        return np.asarray(out, dtype=np.float64).reshape(rgb.shape) ** GAMMA
    adobe = pathlib.Path(ColorSpaceRegistry.get_icc_path(WORKING_COLOR_SPACE)).read_bytes()
    u16 = np.round(enc * 65535).astype(np.uint16).reshape(-1, 1, 3)
    out = imagecodecs.cms_transform(u16, icc, adobe, colorspace="RGB", outcolorspace="RGB", intent=1, flags=0x2000)
    return (out.reshape(rgb.shape) / 65535.0) ** GAMMA


def stock(rgb, m):
    """A Digital print of these colors re-mixed by dye coupling m, black point compensated as the kernel does."""
    d = -np.log10(rgb * (1 - BLACK) + BLACK)
    return np.clip((10.0 ** -(d @ m.T) - BLACK) / (1 - BLACK), 0, 1)


def to_lab(rgb):
    return lab(rgb @ ADOBE_TO_XYZ.T)


def frame(path, max_pixels=250_000):
    """Linear Adobe RGB pixels of a NegPy export, subsampled."""
    a = imagecodecs.imread(str(path))[..., :3]
    a = a.astype(np.float64) / np.iinfo(a.dtype).max if a.dtype.kind == "u" else a.astype(np.float64)
    step = max(1, int(np.ceil(np.sqrt(a.shape[0] * a.shape[1] / max_pixels))))
    return np.clip(a[::step, ::step].reshape(-1, 3), 0, 1) ** GAMMA


def chroma_hue(L):
    return np.hypot(L[:, 1], L[:, 2]), np.degrees(np.arctan2(L[:, 2], L[:, 1])) % 360


def where(digital, target, mixed, d):
    """Where the misses sit: per 30° hue range of the colored pixels, and how many of them are dark."""
    c0, h = chroma_hue(digital)
    ct, cs = chroma_hue(target)[0], chroma_hue(mixed)[0]
    sel = c0 > 8
    print("   by hue, pixels with C* over 8: share, chroma kept vs Digital by the profile / the stock, dE00 mean")
    for lo in range(0, 360, 30):
        m = sel & (h >= lo) & (h < lo + 30)
        if m.sum() >= 0.03 * sel.sum():
            print(
                f"      {lo:3d}-{lo + 30:3d}°  {m.sum() / sel.sum() * 100:4.1f} %   x{np.median(ct[m] / c0[m]):.2f} / x{np.median(cs[m] / c0[m]):.2f}   {d[m].mean():.2f}"
            )
    if (d > 1).any():
        print(f"   pixels over 1 with L* under 50: {np.mean(digital[d > 1, 0] < 50) * 100:.0f} %")


def spread(d):
    return f"{d.mean():5.2f} / {np.percentile(d, 95):5.2f}   {np.mean(d > 1) * 100:4.0f} % {np.mean(d > 2) * 100:5.1f} % {np.mean(d > 3) * 100:5.1f} %"


def main():
    ap = argparse.ArgumentParser(description="Fit a print stock dye coupling to an RGB profile.")
    ap.add_argument("icc", nargs="?", type=pathlib.Path, default=REPO / "tests" / "fixtures" / "RGBScan.icc")
    ap.add_argument("--stock", help="a PAPER_PROFILES key whose shipped matrix to compare")
    ap.add_argument("--images", nargs="+", type=pathlib.Path, default=[], help="NegPy exports on the Digital stock")
    args = ap.parse_args()
    icc = args.icc.read_bytes()
    cls, space, pcs, creator, desc, targ = header(icc)
    path = "primaries only (matrix/TRC)" if is_matrix_trc_profile(icc) else "full CMS"
    print(f"{args.icc.name}: class {cls}, space {space}, PCS {pcs}, creator '{creator}', '{desc}'")
    print(f"applied as NegPy applies an Input ICC: {path}")
    if targ:
        raise SystemExit(
            "CHARACTERIZATION: the profile carries a targ measurement table, so it removes one device's color and holds no look"
        )

    gray = np.geomspace(0.003, 1.0, 24)[:, None] * np.ones(3)
    g_in, g_out = to_lab(gray), to_lab(profile_on_adobe(gray, icc))
    drift = de2000(g_in, g_out)
    mid = int(np.argmin(np.abs(g_in[:, 0] - 50)))
    print(
        f"neutral axis: max dE00 {drift.max():.2f}; mid-gray L* {g_in[mid, 0]:.1f} -> {g_out[mid, 0]:.1f}; "
        f"gray C* up to {np.hypot(g_out[:, 1], g_out[:, 2]).max():.2f}"
    )
    if drift.max() > NEUTRAL_LIMIT:
        raise SystemExit("MOVES NEUTRALS: a stock keeps Digital's grays, so a dye matrix cannot follow this profile")

    rgb = grid()
    target = to_lab(profile_on_adobe(rgb, icc))

    def error(m):
        return de2000(to_lab(stock(rgb, m)), target)

    fitted = coupling(levenberg_marquardt(lambda o: error(coupling(o)), np.zeros(6)))
    shipped = None
    if args.stock:
        shipped = np.array(PAPER_PROFILES[args.stock].dye_matrix, dtype=float)
        shipped /= shipped.sum(1, keepdims=True)
    print(f"\n{len(rgb)} grid colors, dE00 mean / p95:")
    for name, m in (("Digital, no coupling", np.eye(3)), (f"papers.py {args.stock}", shipped), ("fitted", fitted)):
        if m is not None:
            e = error(m)
            print(f"   {name:24s} {e.mean():5.2f} / {np.percentile(e, 95):5.2f}")
    rows = ",\n".join(f"        ({', '.join(f'{v:.4f}' for v in r)})" for r in fitted)
    print(f"   dye_matrix=(\n{rows},\n    ),")
    fitted_lab = to_lab(stock(rgb, fitted))
    near = sorted(
        (de2000(to_lab(stock(rgb, m)), fitted_lab).mean(), p.label)
        for k, p in PAPER_PROFILES.items()
        if k != args.stock and (m := resolve_dye_matrix(p)) is not None
    )
    print("   closest shipped dyes on Digital's curve, dE00 mean: " + ", ".join(f"{label} {d:.2f}" for d, label in near[:3]))

    if args.images:
        m = fitted if shipped is None else shipped
        print(
            f"\nreal frames, dE00 to the profile: mean / p95, share over 1, 2, 3  ({'shipped' if shipped is not None else 'fitted'} matrix)"
        )
        pool = []
        for path in args.images:
            x = frame(path)
            labs = (to_lab(x), to_lab(profile_on_adobe(x, icc)), to_lab(stock(x, m)))
            pool.append(labs)
            ds, dd = de2000(labs[2], labs[1]), de2000(labs[0], labs[1])
            print(f"   {path.name}\n      stock    {spread(ds)}\n      Digital  {spread(dd)}")
        digital, target, mixed = (np.vstack(a) for a in zip(*pool))
        ds = de2000(mixed, target)
        print(f"   all pixels\n      stock    {spread(ds)}\n      Digital  {spread(de2000(digital, target))}")
        where(digital, target, mixed, ds)


if __name__ == "__main__":
    main()
