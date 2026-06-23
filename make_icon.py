"""Gera assets/icon.ico com o design PDF VOZ."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def draw_icon(size: int) -> Image.Image:
    s = size
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = s // 6
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=(30, 58, 138, 255))

    m = int(s * 0.12)
    dw = int(s * 0.56)
    dh = int(s * 0.72)
    dx, dy = m, int(s * 0.10)
    fold = int(s * 0.22)

    doc_poly = [
        (dx, dy),
        (dx + dw - fold, dy),
        (dx + dw, dy + fold),
        (dx + dw, dy + dh),
        (dx, dy + dh),
    ]
    d.polygon(doc_poly, fill=(248, 250, 255, 255))

    fold_tri = [
        (dx + dw - fold, dy),
        (dx + dw, dy),
        (dx + dw, dy + fold),
    ]
    d.polygon(fold_tri, fill=(147, 197, 253, 255))

    banner_y1 = dy + int(dh * 0.40)
    banner_y2 = dy + int(dh * 0.68)
    d.rectangle([dx, banner_y1, dx + dw, banner_y2], fill=(220, 38, 38, 255))

    font_size = max(6, int((banner_y2 - banner_y1) * 0.72))
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    text = "PDF"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = dx + (dw - tw) // 2
    ty = banner_y1 + (banner_y2 - banner_y1 - th) // 2 - bbox[1]
    d.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    line_y = banner_y2 + int(dh * 0.07)
    line_h = max(2, int(s * 0.025))
    lm = dx + int(dw * 0.10)
    for i in range(3):
        y = line_y + i * int(line_h * 2.4)
        w = dw - int(dw * 0.20) if i == 2 else dw - int(dw * 0.10)
        d.rounded_rectangle([lm, y, lm + w, y + line_h], radius=line_h // 2,
                             fill=(191, 219, 254, 255))

    wave_x = dx + dw + int(s * 0.04)
    cy = s // 2
    for i, (amp, thick, alpha) in enumerate([
        (int(s * 0.10), max(2, int(s * 0.025)), 200),
        (int(s * 0.16), max(2, int(s * 0.020)), 160),
        (int(s * 0.22), max(1, int(s * 0.015)), 120),
    ]):
        wx = wave_x + i * int(s * 0.06)
        color = (245, 158, 11, alpha)
        span = amp
        step = max(1, span // 8)
        pts = []
        for y_off in range(-span, span + step, step):
            import math
            x_off = int(amp * 0.5 * math.sin(math.pi * y_off / span))
            pts.append((wx + x_off, cy + y_off))
        if len(pts) >= 2:
            d.line(pts, fill=color, width=thick, joint='curve')

    return img


def main():
    out = Path(__file__).parent / 'assets' / 'icon.ico'
    out.parent.mkdir(exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 16]
    images = [draw_icon(s) for s in sizes]
    images[0].save(
        str(out), format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f'Ícone gerado: {out}  ({out.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
