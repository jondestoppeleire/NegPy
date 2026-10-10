"""Color vision: one Preferences choice, read by every view that tells things apart by hue alone.

A palette names roles, not hues, so a view asks for its role and gets colors that vision keeps.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VisionPalette:
    key: str
    label: str
    pair: tuple[str, str]  # two kinds of mark that must read apart over any image


# Standard is neon: a mark has to read over any film. The color-blind pairs are Okabe–Ito
# (Color Universal Design) colors on an axis that vision keeps.
PALETTES: tuple[VisionPalette, ...] = (
    VisionPalette("standard", "Standard", ("#39FF14", "#FF00FF")),
    VisionPalette("protan_deutan", "Protanopia / deuteranopia (red-green)", ("#56B4E9", "#E69F00")),
    VisionPalette("tritan", "Tritanopia (blue-yellow)", ("#D55E00", "#009E73")),
    VisionPalette("achromat", "Achromatopsia (no color)", ("#FFFFFF", "#000000")),
)


def palette_for(key: str) -> VisionPalette:
    return next((p for p in PALETTES if p.key == key), PALETTES[0])
