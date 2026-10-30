"""그림을 도트(픽셀아트)로: 줄이기 → 색 줄이기(팔레트) → 투명 배경 정리 → (외곽선) → 확대 미리보기."""
from PIL import Image


def _palette_image(rgb_list):
    flat = [c for rgb in rgb_list for c in rgb]
    flat += list(rgb_list[0]) * (256 - len(rgb_list))  # 빈 칸을 첫 색으로 채워야 검정이 끼어들지 않는다
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat)
    return pal


def _hex(hx):
    hx = hx.lstrip("#")
    return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))


def _auto_palette(img, alpha, count):
    """불투명한 곳의 색만 보고 count 가지 색을 고른다."""
    px = [p for p, a in zip(img.getdata(), alpha.getdata()) if a]
    if not px:
        px = list(img.getdata())
    flat = Image.new("RGB", (len(px), 1))
    flat.putdata(px)
    q = flat.quantize(colors=max(2, min(64, count)), method=Image.Quantize.MEDIANCUT, kmeans=4)
    used = sorted({i for _, i in q.getcolors()})
    return [tuple(q.getpalette()[i * 3:i * 3 + 3]) for i in used]


def _outline(img, color):
    """불투명한 모양 바깥에 1픽셀 외곽선."""
    w, h = img.size
    canvas = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    canvas.paste(img, (1, 1))
    a = canvas.getchannel("A").load()
    px = canvas.load()
    edge = [(x, y) for y in range(h + 2) for x in range(w + 2) if a[x, y] == 0 and any(
        0 <= x + dx < w + 2 and 0 <= y + dy < h + 2 and a[x + dx, y + dy] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    for x, y in edge:
        px[x, y] = color + (255,)
    return canvas


def to_pixel(im, params, colors=None):
    """그림 한 장을 도트로. colors 를 주면 그 색만 쓴다 (애니메이션 프레임끼리 색을 맞출 때)."""
    size = int(params.get("size") or 64)
    rgba = im.convert("RGBA")
    solid = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    box = solid.getbbox()
    if box and params.get("trim", True):  # 빈 여백을 잘라 내서 캐릭터가 칸을 꽉 채우게
        rgba = rgba.crop(box)
    w, h = rgba.size
    inner = size - 2 if params.get("outline") else size  # 외곽선 1픽셀씩 자리를 남긴다
    s = inner / max(w, h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    small = rgba.convert("RGBa").resize((nw, nh), Image.Resampling.BOX).convert("RGBA")  # 투명한 곳 색이 번지지 않게
    alpha = small.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    rgb = small.convert("RGB")
    if colors is None:
        colors = pick_colors([im], params)
    q = rgb.quantize(palette=_palette_image(colors), dither=Image.Dither.NONE).convert("RGBA")
    q.putalpha(alpha)
    if params.get("outline"):
        lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        darkest = min(colors, key=lum)
        if lum(darkest) > 60:  # 팔레트에 어두운 색이 없으면 가장 어두운 색을 더 어둡게
            darkest = tuple(int(v * 0.3) for v in darkest)
        q = _outline(q, darkest)
    if params.get("square", True):  # size x size 칸 아래 가운데에 놓기 (게임 칸 크기를 맞추려고)
        cell = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        cell.paste(q, ((size - q.width) // 2, size - q.height))
        q = cell
    return q


def pick_colors(images, params):
    """팔레트를 골랐으면 그 색, 아니면 그림들(여러 장이면 합쳐서)에서 색 수만큼 고른다."""
    pal = params.get("palette") or {}
    if pal.get("colors"):
        return [_hex(c) for c in pal["colors"]]
    count = int(params.get("colors") or 16)
    thumbs = []
    for im in images:
        t = im.convert("RGBA")
        t.thumbnail((128, 128))
        thumbs.append(t)
    sheet = Image.new("RGBA", (sum(t.width for t in thumbs), max(t.height for t in thumbs)), (0, 0, 0, 0))
    x = 0
    for t in thumbs:
        sheet.paste(t, (x, 0))
        x += t.width
    alpha = sheet.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    return _auto_palette(sheet.convert("RGB"), alpha, count)


def run(images, params):
    out = []
    for im, name in images:
        q = to_pixel(im, params)
        k = max(1, 512 // max(q.size))
        out.append((q, name, f"실제 {q.width}x{q.height}"))
        out.append((q.resize((q.width * k, q.height * k), Image.Resampling.NEAREST), name, f"{k}배 확대 미리보기"))
    return out
