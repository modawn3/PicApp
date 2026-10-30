"""프레임 여러 장 → 스프라이트 시트 (+ 움직임 미리보기 GIF). 도트로 바꾸기도 고를 수 있다.

모든 프레임을 같은 비율로 줄인다 (프레임마다 따로 맞추면 팔을 든 프레임만 캐릭터가 작아진다).
"""
import importlib.util
import os

from PIL import Image

_spec = importlib.util.spec_from_file_location("pp_pixel_for_sprite", os.path.join(os.path.dirname(__file__), "pixel.py"))
pixel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pixel)


def _same_canvas(frames):
    """프레임마다 빈 여백을 자르고, 가장 큰 프레임 크기의 칸에 아래 가운데로 놓는다."""
    cut = []
    for im in frames:
        im = im.convert("RGBA")
        box = im.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()
        cut.append(im.crop(box) if box else im)
    w, h = max(c.width for c in cut), max(c.height for c in cut)
    out = []
    for c in cut:
        cell = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cell.paste(c, ((w - c.width) // 2, h - c.height))
        out.append(cell)
    return out


def _fit(im, cell):
    """cell x cell 칸 아래 가운데에 맞춘다."""
    s = cell / max(im.size)
    small = im.convert("RGBa").resize((max(1, round(im.width * s)), max(1, round(im.height * s))),
                                      Image.Resampling.LANCZOS).convert("RGBA")
    out = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    out.paste(small, ((cell - small.width) // 2, cell - small.height))
    return out


def run(images, params):
    if not images:
        return []
    frames = _same_canvas([im for im, _ in images])
    name = images[0][1]
    if params.get("pixel"):
        p = dict(params, trim=False, square=True)
        colors = pixel.pick_colors(frames, p)  # 모든 프레임이 같은 색을 쓰게
        cells = [pixel.to_pixel(f, p, colors) for f in frames]
    else:
        cell = int(params.get("cell") or 0)
        cells = [_fit(f, cell) for f in frames] if cell else frames
    cw, ch = cells[0].size
    n = len(cells)
    cols = int(params.get("columns") or 0) or n
    cols = min(cols, n)
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGBA", (cw * cols, ch * rows), (0, 0, 0, 0))
    for i, c in enumerate(cells):
        sheet.paste(c, ((i % cols) * cw, (i // cols) * ch))
    info = f"{n}칸, 칸 {cw}x{ch}, {cols}열 {rows}줄"
    ms = int(params.get("frame_ms") or 120)
    # "sheet": 그림 도구가 Aseprite 로 열 때 프레임을 나누는 정보
    out = [(sheet, name, f"시트 {info}", {"sheet": {"cell": [cw, ch], "count": n, "cols": cols, "ms": ms}})]
    k = max(1, 384 // max(cw, ch)) if params.get("pixel") else 1
    if k > 1:
        out.append((sheet.resize((sheet.width * k, sheet.height * k), Image.Resampling.NEAREST), name, f"시트 {k}배 확대 미리보기"))
    # 움직임 미리보기: GIF 는 반투명을 못 써서 밝은 회색 바탕에 얹는다
    gif = []
    for c in cells:
        bg = Image.new("RGBA", c.size, (232, 232, 232, 255))
        bg.alpha_composite(c)
        if k > 1:
            bg = bg.resize((c.width * k, c.height * k), Image.Resampling.NEAREST)
        gif.append(bg.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=255))
    out.append((gif[0], name, f"움직임 미리보기 {ms}ms", {"ext": "gif", "frames": gif, "duration": ms}))
    return out
