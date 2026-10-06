# -*- coding: utf-8 -*-
"""戰情室圖示（2026-10-07，Leo：「windows 列表的小圖看起來很不專業」）。程式現畫、原創圖形，不引用任何外部圖。
深藍圓角底＋三根蠟燭＋向上折線（青色）與終點亮點（琥珀）；用 4 倍超取樣縮小，小尺寸也清楚。
  png(size)  → bytes（網頁 favicon／apple-touch-icon，bot 的 /app-icon.png 用）
  write_ico(path) → 多尺寸 .ico（桌面捷徑與工作列用）
"""
import io
import os
import tempfile

from PIL import Image, ImageDraw

BG1, BG2 = (10, 18, 34), (4, 8, 16)
CYAN, AMBER, UP, DOWN = (34, 211, 238), (245, 184, 65), (34, 197, 94), (239, 68, 68)


def _draw(n=1024):
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    # 圓角底（上亮下暗的漸層）
    grad = Image.new("RGBA", (n, n))
    gd = ImageDraw.Draw(grad)
    for y in range(n):
        t = y / n
        gd.line([(0, y), (n, y)], fill=tuple(int(BG1[i] * (1 - t) + BG2[i] * t) for i in range(3)) + (255,))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.22), fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((int(n * .035),) * 2 + (int(n * .965),) * 2, radius=int(n * .19), outline=(34, 211, 238, 90), width=int(n * .012))
    # 蠟燭（左→右：小、中、大；紅綠依台股慣例不重要，這裡只用綠色表上漲）
    base = int(n * .78)
    cw = int(n * .12)
    for cx, top, bot, col in ((.27, .52, .76, UP), (.47, .40, .66, UP), (.67, .27, .56, UP)):
        x = int(n * cx)
        d.line([(x, int(n * (top - .06))), (x, int(n * (bot + .05)))], fill=col, width=int(n * .02))
        d.rounded_rectangle((x - cw // 2, int(n * top), x + cw // 2, int(n * bot)), radius=int(n * .015), fill=col)
    # 趨勢線與終點亮點
    pts = [(.17, .70), (.34, .58), (.50, .50), (.66, .36), (.82, .22)]
    pp = [(int(n * a), int(n * b)) for a, b in pts]
    d.line(pp, fill=CYAN, width=int(n * .045), joint="curve")
    r = int(n * .06)
    d.ellipse((pp[-1][0] - r, pp[-1][1] - r, pp[-1][0] + r, pp[-1][1] + r), fill=AMBER, outline=(4, 8, 16), width=int(n * .015))
    d.line([(int(n * .14), base + int(n * .07)), (int(n * .86), base + int(n * .07))], fill=(34, 211, 238, 110), width=int(n * .014))
    return im


def png(size=512):
    im = _draw().resize((size, size), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def write_ico(path):
    """每個尺寸都從 1024 母圖用 LANCZOS 各自縮出來再封裝（PIL 預設只吃單張、縮小品質差，小圖會糊）。"""
    big = _draw()
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    imgs = [big.resize((n, n), Image.LANCZOS) for n in sizes]
    imgs[-1].save(path, format="ICO", sizes=[(n, n) for n in sizes], append_images=imgs[:-1])


if __name__ == "__main__":
    write_ico("戰情室.ico")
    open(os.path.join(tempfile.gettempdir(), "app_icon_preview.png"), "wb").write(png(256))   # 預覽放系統暫存，不放 state/
    print("ok")
