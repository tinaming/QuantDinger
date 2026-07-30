"""Generate ChanQuant brand PNG assets (idempotent)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "frontend_override" / "html"
ASSETS = HTML / "assets"

CYAN = (19, 194, 194, 255)  # #13C2C2
NAVY = (26, 26, 46, 255)  # #1a1a2e
WHITE = (255, 255, 255, 255)
DARK_TEXT = (15, 23, 42, 255)
MUTED = (100, 116, 139, 255)
MUTED_LIGHT = (148, 163, 184, 255)


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_mark(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, fill, accent) -> None:
    half = size // 2
    box = [cx - half, cy - half, cx + half, cy + half]
    draw.rounded_rectangle(box, radius=max(6, size // 5), fill=fill)
    font = _font(int(size * 0.58), bold=True)
    bbox = draw.textbbox((0, 0), "C", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), "C", font=font, fill=accent)


def make_wordmark(width: int, height: int, *, dark: bool, with_tagline: bool = False) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    mark_size = int(height * 0.72)
    pad = int(height * 0.14)
    cx = pad + mark_size // 2
    cy = height // 2
    draw_mark(draw, cx, cy, mark_size, CYAN if not dark else WHITE, NAVY if not dark else CYAN)

    title_font = _font(int(height * 0.42), bold=True)
    tx = cx + mark_size // 2 + int(height * 0.18)
    ty = (height - int(height * 0.42)) // 2 - (int(height * 0.08) if with_tagline else 0)
    draw.text((tx, ty), "ChanQuant", font=title_font, fill=WHITE if dark else DARK_TEXT)

    if with_tagline:
        tag_font = _font(max(12, int(height * 0.16)), bold=False)
        draw.text(
            (tx, ty + int(height * 0.48)),
            "Clarity in Structure",
            font=tag_font,
            fill=MUTED_LIGHT if dark else MUTED,
        )
    return img


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_mark(draw, size // 2, size // 2, int(size * 0.92), NAVY, CYAN)
    return img


def save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def main() -> None:
    save(make_wordmark(640, 160, dark=False, with_tagline=True), ASSETS / "logo-CDyfYTxu.png")
    save(make_wordmark(640, 160, dark=True, with_tagline=True), ASSETS / "logo_w-CQ4B3CRZ.png")
    save(make_icon(256), ASSETS / "slogo-N1Ib8St6.png")
    save(make_wordmark(480, 120, dark=False, with_tagline=False), HTML / "logo.png")
    save(make_icon(256), HTML / "slogo.png")


if __name__ == "__main__":
    main()
