"""Generate multi-resolution assets/kablocast.ico for the Windows desktop executable."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def draw_kablocast_icon(size: int = 512) -> Image.Image:
    """Render a crisp Cobalt & Slate rounded-square KabloCast app icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(size * 0.06)
    radius = int(size * 0.22)
    bg_box = [pad, pad, size - pad, size - pad]

    # Deep slate rounded background + crisp cobalt border
    draw.rounded_rectangle(
        bg_box,
        radius=radius,
        fill=(23, 32, 48, 255),
        outline=(59, 130, 246, 255),
        width=max(4, int(size * 0.025)),
    )

    # Phone silhouette on the left
    phone_w = int(size * 0.28)
    phone_h = int(size * 0.50)
    px0 = int(size * 0.20)
    py0 = (size - phone_h) // 2
    stroke = max(4, int(size * 0.042))
    draw.rounded_rectangle(
        [px0, py0, px0 + phone_w, py0 + phone_h],
        radius=max(6, int(size * 0.055)),
        fill=(30, 41, 59, 255),
        outline=(59, 130, 246, 255),
        width=stroke,
    )

    # Home indicator / status dot inside phone
    dot_r = max(3, int(size * 0.024))
    dcx = px0 + phone_w // 2
    dcy = py0 + phone_h - int(size * 0.075)
    draw.ellipse([dcx - dot_r, dcy - dot_r, dcx + dot_r, dcy + dot_r], fill=(16, 185, 129, 255))

    # Streaming arcs / screen mirror link on the right
    arc_cx = px0 + phone_w - int(size * 0.02)
    arc_cy = size // 2
    for idx, factor in enumerate((0.18, 0.31)):
        rad = int(size * factor)
        color = (16, 185, 129, 255) if idx == 0 else (96, 165, 250, 255)
        draw.arc(
            [arc_cx - rad, arc_cy - rad, arc_cx + rad, arc_cy + rad],
            start=-52,
            end=52,
            fill=color,
            width=max(4, int(size * 0.045)),
        )

    return img


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out_path = root / "assets" / "kablocast.ico"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    master = draw_kablocast_icon(512)
    master.save(
        out_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Generated {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
