"""Geçici uygulama simgesi (ürün görsel kimliği kesinleşene kadar).

Çalıştırma (depo kökünden):
    uv run --with pillow apps/desktop/src-tauri/icons/make_icon.py
    cd apps/desktop && npx.cmd tauri icon src-tauri/icons/source.png
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=(47, 111, 94, 255))
w = 92
d.line([(260, 800), (512, 220), (764, 800)], fill=(255, 255, 255, 255), width=w, joint="curve")
d.line([(360, 590), (664, 590)], fill=(255, 255, 255, 255), width=w - 10)
d.ellipse((472, 120, 552, 200), fill=(201, 236, 222, 255))
img.save(Path(__file__).with_name("source.png"))
