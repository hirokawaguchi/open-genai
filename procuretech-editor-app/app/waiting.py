"""待ち画像のフォールバック（生成サービスが返せないとき用）。"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw


def make_fallback_waiting_png(size: int = 512) -> bytes:
    """白背景に、子どもの落書き風のロボットを描いた PNG を返す。"""
    img = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    ink = (40, 40, 50)
    draw.ellipse((170, 70, 350, 240), outline=ink, width=7)
    draw.ellipse((210, 130, 245, 165), outline=ink, width=5)
    draw.ellipse((275, 128, 312, 168), outline=ink, width=5)
    draw.ellipse((222, 142, 234, 154), fill=ink)
    draw.ellipse((288, 140, 300, 154), fill=ink)
    draw.arc((230, 175, 300, 215), start=10, end=170, fill=ink, width=5)
    draw.line((260, 70, 248, 28), fill=ink, width=5)
    draw.ellipse((236, 12, 262, 38), outline=ink, width=5)
    draw.rounded_rectangle((175, 250, 345, 400), radius=18, outline=ink, width=7)
    draw.rectangle((220, 290, 300, 345), outline=ink, width=4)
    draw.line((175, 280, 90, 340), fill=ink, width=7)
    draw.line((345, 275, 430, 330), fill=ink, width=7)
    draw.ellipse((68, 322, 108, 362), outline=ink, width=5)
    draw.ellipse((412, 312, 454, 354), outline=ink, width=5)
    draw.line((220, 400, 200, 480), fill=ink, width=7)
    draw.line((300, 400, 330, 478), fill=ink, width=7)
    draw.ellipse((175, 468, 230, 500), outline=ink, width=5)
    draw.ellipse((308, 466, 368, 500), outline=ink, width=5)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
