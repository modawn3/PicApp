"""그린 그림의 모든 색을 팔레트 색 중 가장 가까운 색으로 바꾼다. 투명도는 그대로 둔다."""
from PIL import Image


def _palette_image(colors):
    rgb = []
    for hx in colors:
        hx = hx.lstrip("#")
        rgb += [int(hx[i:i + 2], 16) for i in (0, 2, 4)]
    n = len(rgb) // 3
    rgb += rgb[:3] * (256 - n)  # 빈 칸을 첫 색으로 채워야 검정이 끼어들지 않는다
    pal = Image.new("P", (1, 1))
    pal.putpalette(rgb)
    return pal


def run(images, params):
    pal = _palette_image(params["colors"])
    dither = Image.Dither.FLOYDSTEINBERG if params.get("dither") else Image.Dither.NONE
    out = []
    for im, name in images:
        rgba = im.convert("RGBA")
        snapped = rgba.convert("RGB").quantize(palette=pal, dither=dither).convert("RGBA")
        snapped.putalpha(rgba.getchannel("A"))
        out.append((snapped, name))
    return out
