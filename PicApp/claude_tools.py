"""Claude 연결 장치의 기능들 (claude_mcp.py 가 불러 쓴다).

켜져 있는 그림 도구(server.py, http://127.0.0.1:8190)에 주문을 넣고 결과 그림을 돌려준다.
기능(탭) 목록은 presets 폴더에서 그때그때 읽으므로 새 탭이 생겨도 여기는 고칠 필요가 없다.
그림 입력은 이 컴퓨터의 파일 경로로 받는다 (Claude 가 대화에 올린 그림을 직접 넘길 수는 없어서).
"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PRESET_DIR = os.path.join(APP_DIR, "presets")
RESULT_DIR = os.path.join(APP_DIR, "results")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
WAIT_DEFAULT = 50  # 한 번에 기다리는 초. 넘으면 picapp_job 으로 이어서 기다린다

INSTRUCTIONS = """그림 도구(PicApp)는 이 컴퓨터의 ComfyUI(Stable Diffusion 1.5 위주)를 버튼식으로 쓰는 프로그램이에요.
- 처음에 picapp_features 로 기능(탭)과 칸을 확인하세요. 기능은 업데이트로 늘어날 수 있어요.
- 그리기는 picapp_run. 안 넣은 칸은 그림 도구의 기본값을 써요. 그림 칸에는 이 컴퓨터의 파일 경로를 넣어요.
- 프롬프트는 영어로, 명령문이 아니라 결과 모습을 쓰고, 없앨 것은 부정 칸에 써요. 한글은 저절로 번역돼요.
- 결과로 나온 파일 경로를 다음 기능의 그림 칸에 그대로 넣으면 이어서 고칠 수 있어요.
- 오래 걸리면 picapp_run 이 job_id 를 돌려줘요. picapp_job 으로 이어서 기다려요.
- 사용자가 "방금 그린 그림"이라고 하면 picapp_recent 로 찾으세요."""


def version():
    try:
        st = os.stat(__file__)
        return time.strftime("%Y.%m.%d.%H%M", time.localtime(st.st_mtime))
    except OSError:
        return "0"


class ToolError(Exception):
    pass


# ---------- 그림 도구 서버와 대화 ----------

def settings():
    s = {"port": 8190}
    try:
        with open(os.path.join(APP_DIR, "settings.json"), encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def base_url():
    return f"http://127.0.0.1:{int(settings()['port'])}"


def api(path, data=None, timeout=30, raw=False):
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(base_url() + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read()
            return out if raw else json.loads(out or b"null")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except ValueError:
            msg = None
        raise ToolError(msg or f"그림 도구 응답 오류 {e.code}")


def server_up():
    try:
        return api("/api/status", timeout=5)
    except (urllib.error.URLError, OSError, ToolError):
        return None


def start_server():
    py = os.path.join(APP_DIR, "server.py")
    if os.name == "nt":  # 평소처럼 검은 창으로 뜬다 (끄려면 그 창을 닫는다)
        try:  # Claude 를 꺼도 그림 도구는 켜져 있게
            subprocess.Popen([sys.executable, "-s", py, "--no-browser"], cwd=APP_DIR,
                             creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            subprocess.Popen([sys.executable, "-s", py, "--no-browser"], cwd=APP_DIR,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        logf = open(os.path.join(APP_DIR, "server_from_claude.log"), "ab")
        subprocess.Popen([sys.executable, "-s", py, "--no-browser"], cwd=APP_DIR, stdin=subprocess.DEVNULL,
                         stdout=logf, stderr=logf, start_new_session=True)


def ensure_ready(progress, need_comfy=True, wait=150):
    """그림 도구가 꺼져 있으면 켜고, ComfyUI 가 준비될 때까지 기다린다."""
    st = server_up()
    started = False
    if st is None:
        start_server()
        started = True
    t0 = time.time()
    while time.time() - t0 < wait:
        if st is not None and (st.get("comfy") or not need_comfy):
            return st
        progress("그림 도구를 켜는 중" if st is None else "ComfyUI 가 켜지기를 기다리는 중")
        time.sleep(2)
        st = server_up()
    if st is None:
        raise ToolError("그림 도구가 켜지지 않았어요. C:\\AI-PIC\\PicApp\\그림도구_실행.bat 을 직접 켜 보세요.")
    raise ToolError("ComfyUI 가 켜지지 않았어요." + (" 그림 도구는 켰어요." if started else "")
                    + " ComfyUI 검은 창에 오류가 있는지 확인하세요.")


# ---------- 기능(탭) ----------

def load_presets():
    out = []
    for folder in sorted(os.listdir(PRESET_DIR)):
        path = os.path.join(PRESET_DIR, folder, "preset.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["id"] = folder
            out.append(cfg)
    return out


def find_preset(name):
    presets = load_presets()
    for p in presets:
        if name in (p["id"], p.get("name")):
            return p
    for p in presets:  # "캐릭터" 처럼 일부만 말해도
        if name and (name in p.get("name", "") or p["id"].split("_", 1)[-1] == name):
            return p
    raise ToolError(f"'{name}' 기능이 없어요. 있는 것: " + ", ".join(f"{p['id']} ({p.get('name')})" for p in presets))


TYPE_HELP = {
    "text": "글자", "textarea": "글자 (영어 프롬프트)", "number": "숫자", "toggle": "켜기/끄기 (true/false)",
    "choice": "options 의 value 중 하나", "seed": "정수. 비우거나 -1 이면 매번 새로",
    "image": "그림 파일 경로", "images": "그림 파일 경로 목록 (순서대로)",
    "mask_image": '{"image": 경로, "boxes": [[x0,y0,x1,y1], ...]} 고칠 곳 상자 (0~1 비율, 왼쪽 위 기준). '
                  '또는 {"image": 경로, "mask": 마스크 그림 경로 (흰색 = 고칠 곳)}',
    "palette": "저장된 팔레트 이름, 또는 [\"#rrggbb\", ...] 색 목록. 안 쓰려면 비움",
    "loras": "LoRA 파일 이름 목록, 또는 [{\"name\": 이름, \"strength\": 0.8}]",
}


def describe_field(f):
    d = {"id": f["id"], "type": f["type"], "label": f.get("label")}
    for k in ("default", "min", "max", "step", "hint"):
        if f.get(k) not in (None, ""):
            d[k] = f[k]
    if f.get("required") is False or f["type"] in ("toggle", "seed", "palette", "loras"):
        d["optional"] = True
    if f.get("options"):
        d["options"] = [{"value": o["value"], "label": o.get("label")} for o in f["options"]]
    if f.get("auto_from") or f.get("auto_alpha_from") or f.get("skeleton_for"):
        d["auto"] = "그림을 넣으면 저절로 맞춰져요 (직접 넣으면 그 값)"
    return d


def describe_preset(p, detail):
    d = {"id": p["id"], "name": p.get("name"), "group": p.get("group"), "description": p.get("description")}
    if p.get("tool"):
        d["note"] = "그림 도구 화면에서만 쓰는 도구라 여기서는 못 써요"
        return d
    if detail:
        d["fields"] = [describe_field(f) for f in p.get("fields", [])]
        d["outputs"] = [o["label"] for o in p.get("outputs", []) if not o.get("hidden")]
        if p.get("repeat_over"):
            d["note"] = f"'{p['repeat_over']}' 칸의 그림마다 한 장씩 같은 시드로 그려요 (최대 24장)"
    else:
        need = [f["id"] for f in p.get("fields", []) if f["type"] in ("image", "images", "mask_image")
                and f.get("required", True)]
        d["fields"] = [f["id"] for f in p.get("fields", [])]
        if need:
            d["needs_image"] = need
    return d


def palettes():
    out = []
    d = os.path.join(APP_DIR, "palettes")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if fn.endswith(".json"):
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    out.append({**json.load(f), "file": fn})
            except (OSError, ValueError):
                pass
    return out


def loras():
    try:
        return api("/api/loras", timeout=10) if server_up() else None
    except ToolError:
        return None


# ---------- 칸 값 만들기 (그림 도구 화면이 하는 일을 똑같이) ----------

def open_image(path):
    from PIL import Image

    path = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    if not os.path.isabs(path):
        for base in (RESULT_DIR, comfy_output_dir() or "", APP_DIR):
            if base and os.path.isfile(os.path.join(base, path)):
                path = os.path.join(base, path)
                break
    if not os.path.isfile(path):
        raise ToolError(f"그림 파일이 없어요: {path}")
    img = Image.open(path)
    img.load()
    return img


def has_alpha(img):
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        return img.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return False


def flatten(img):
    from PIL import Image

    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


def to_data_url(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def is_skeleton(img):
    """검은 바탕에 진한 색 막대만 있으면 OpenPose 뼈대 그림 (web/app.js isSkeleton 과 같음)."""
    small = img.convert("RGBA").resize((64, 64))
    black = vivid = 0
    for r, g, b, a in small.getdata():
        if a < 250:
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if mx < 25:
            black += 1
        elif mx - mn > 90 and mx > 120:
            vivid += 1
    rest = 4096 - black
    return black > 4096 * 0.75 and vivid > 15 and vivid > rest * 0.5


def make_mask(img, spec):
    """칠한 곳 = 알파 255 인 PNG (그림 도구 화면의 붓 칠과 같은 모양)."""
    from PIL import Image, ImageDraw

    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    if spec.get("mask"):
        m = open_image(spec["mask"])
        if has_alpha(m) and m.convert("RGBA").getchannel("A").getextrema()[1] > 0 and \
                m.convert("L").getextrema()[0] == m.convert("L").getextrema()[1]:
            m = m.convert("RGBA").getchannel("A")  # 한 색으로 칠하고 나머지가 투명한 그림
        else:
            m = m.convert("L")
        mask = m.resize((w, h)).point(lambda v: 255 if v > 127 else 0)
    draw = ImageDraw.Draw(mask)
    for box in spec.get("boxes") or []:
        if len(box) != 4:
            raise ToolError("boxes 는 [x0, y0, x1, y1] 목록이에요.")
        x0, y0, x1, y1 = [float(v) for v in box]
        if max(x0, y0, x1, y1) <= 1.0:  # 비율
            x0, x1, y0, y1 = x0 * w, x1 * w, y0 * h, y1 * h
        draw.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], fill=255)
    if mask.getbbox() is None:
        raise ToolError("고칠 곳이 없어요. boxes 나 mask 를 넣어 주세요.")
    out = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    out.putalpha(mask)
    return out


def palette_value(val):
    if not val:
        return None
    if isinstance(val, dict):
        return {"guide": True, "snap": True, **val}
    if isinstance(val, list):
        return {"name": "__custom", "colors": list(val), "guide": True, "snap": True}
    for p in palettes():
        if str(val) in (p.get("name"), os.path.splitext(p.get("file", ""))[0]) or str(val) in p.get("name", ""):
            return {"name": p["name"], "colors": p["colors"], "guide": True, "snap": True}
    raise ToolError(f"'{val}' 팔레트가 없어요. 있는 것: " + ", ".join(p.get("name", "") for p in palettes()))


def lora_value(val):
    names = loras() or []
    out = []
    for x in val or []:
        x = {"name": x} if isinstance(x, str) else dict(x)
        n = x.get("name", "")
        if n and n not in names:  # 확장자나 폴더 없이 말해도
            hit = [m for m in names if os.path.splitext(os.path.basename(m.replace("\\", "/")))[0] == n
                   or os.path.basename(m.replace("\\", "/")) == n]
            if hit:
                n = hit[0]
            elif names:
                raise ToolError(f"LoRA '{n}' 가 없어요. 있는 것: " + ", ".join(names))
        out.append({"name": n, "strength": float(x.get("strength", 0.8)), "word": x.get("word", True) is not False})
    return out


def choice_value(f, val):
    for o in f["options"]:
        if str(val) in (str(o["value"]), str(o.get("label"))):
            return o["value"]
    raise ToolError(f"'{f['id']}' 칸에는 이 중 하나를 넣어요: " + ", ".join(f"{o['value']} ({o.get('label')})" for o in f["options"]))


def prepare_values(preset, given):
    fields = {f["id"]: f for f in preset.get("fields", [])}
    unknown = [k for k in given if k not in fields]
    if unknown:
        raise ToolError(f"없는 칸: {', '.join(unknown)}. 있는 칸: {', '.join(fields)}")
    values, notes = {}, []
    auto = {}  # 그림을 보고 저절로 정하는 칸 (사용자가 안 넣었을 때만)

    def note_auto(fid, value, why):
        if fid not in given and fid in fields:
            auto[fid] = value
            notes.append(f"{fields[fid].get('label', fid)} → {value} ({why})")

    for fid, f in fields.items():
        t = f["type"]
        if fid not in given:
            if t == "toggle":  # 화면은 기본값이 없으면 켜 둔다
                values[fid] = f.get("default", True)
            continue
        val = given[fid]
        if t == "image":
            if val in (None, ""):
                values[fid] = None
                continue
            img = open_image(val)
            alpha = has_alpha(img)
            for g in fields.values():
                if g.get("auto_alpha_from") == fid:
                    o = next((o for o in g["options"] if bool(o.get("alpha")) == alpha), None)
                    if o:
                        note_auto(g["id"], o["value"], "투명한 그림" if alpha else "배경 있는 그림")
            img = flatten(img) if (f.get("flatten") and alpha) else img.convert("RGBA" if alpha else "RGB")
            if f.get("flatten") and alpha:
                notes.append(f"{f.get('label')}: 투명한 곳을 흰색으로 채웠어요")
            values[fid] = to_data_url(img)
            auto_from_image(fields, fid, img, note_auto)
        elif t == "images":
            paths = val if isinstance(val, list) else [val]
            imgs = [open_image(p) for p in paths]
            values[fid] = [to_data_url(i.convert("RGBA") if has_alpha(i) else i.convert("RGB")) for i in imgs]
            if imgs:
                auto_from_image(fields, fid, imgs[0], note_auto)
        elif t == "mask_image":
            spec = val if isinstance(val, dict) else {"image": val}
            if not spec.get("image"):
                raise ToolError(f"'{fid}' 에는 image(그림 경로)와 boxes 또는 mask 가 필요해요.")
            img = open_image(spec["image"])
            if has_alpha(img):
                notes.append("고칠 그림의 투명한 곳을 흰색으로 채웠어요. 배경 있는 원본이 더 좋아요")
            img = flatten(img)
            values[fid] = {"image": to_data_url(img), "mask": to_data_url(make_mask(img, spec))}
        elif t == "palette":
            values[fid] = palette_value(val)
        elif t == "loras":
            values[fid] = lora_value(val if isinstance(val, list) else [val])
        elif t == "choice":
            values[fid] = choice_value(f, val)
        elif t == "toggle":
            values[fid] = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "on", "yes", "켜기")
        elif t == "seed":
            values[fid] = -1 if val in (None, "", -1, "-1", "random") else int(val)
        elif t == "number":
            values[fid] = float(val)
        else:
            values[fid] = "" if val is None else str(val)
    values.update(auto)
    return values, notes


def auto_from_image(fields, fid, img, note_auto):
    w, h = img.size
    for g in fields.values():
        if g.get("auto_from") == fid and g.get("options"):
            best = min(g["options"], key=lambda o: abs(o.get("ratio", 1) - w / h))
            note_auto(g["id"], best["value"], f"그림 비율 {w}x{h}")
        if g.get("skeleton_for") == fid:
            sk = is_skeleton(img)
            note_auto(g["id"], sk, "뼈대 그림" if sk else "보통 그림")


# ---------- 결과 그림 ----------

_dirs = {}


def comfy_output_dir():
    """ComfyUI 의 output 폴더 (server.py output_dir 과 같은 규칙)."""
    if "out" in _dirs:
        return _dirs["out"]
    s = settings()
    d = s.get("output_dir")
    if not d:
        comfy = s.get("comfy_dir") or "..\\ComfyUI_windows_portable"
        comfy = comfy.replace("\\", os.sep)
        if not os.path.isabs(comfy):
            comfy = os.path.normpath(os.path.join(APP_DIR, comfy))
        if not os.path.isdir(comfy) and os.path.isdir(r"C:\AI-PIC\ComfyUI_windows_portable"):
            comfy = r"C:\AI-PIC\ComfyUI_windows_portable"
        d = os.path.join(comfy, "ComfyUI", "output")
    elif not os.path.isabs(d):
        d = os.path.normpath(os.path.join(APP_DIR, d))
    _dirs["out"] = d if os.path.isdir(d) else None
    return _dirs["out"]


def local_path(item):
    """결과 카드의 주소 → 이 컴퓨터의 파일. 임시 그림은 results 에 저장해서 경로를 만든다."""
    u = urllib.parse.urlparse(item["url"])
    q = dict(urllib.parse.parse_qsl(u.query))
    if u.path == "/api/result":
        path = os.path.join(RESULT_DIR, os.path.basename(q.get("name", "")))
        if os.path.isfile(path):
            return path
    if u.path == "/api/image" and q.get("type", "output") == "output" and comfy_output_dir():
        path = os.path.join(comfy_output_dir(), *[x for x in q.get("subfolder", "").split("/") if x],
                            os.path.basename(q.get("filename", "")))
        if os.path.isfile(path):
            return path
    os.makedirs(RESULT_DIR, exist_ok=True)
    path = os.path.join(RESULT_DIR, os.path.basename(q.get("filename") or q.get("name") or "image.png"))
    with open(path, "wb") as f:
        f.write(api(u.path + "?" + u.query, raw=True, timeout=60))
    return path


def preview(img, max_size):
    """Claude 에게 보여 줄 작은 그림. 도트처럼 아주 작은 그림은 각지게 키운다."""
    from PIL import Image

    frames = getattr(img, "n_frames", 1)
    img.seek(0) if frames > 1 else None
    alpha = has_alpha(img)
    im = img.convert("RGBA" if alpha else "RGB")
    w, h = im.size
    if max(w, h) < 256:
        k = max(1, 384 // max(w, h))
        im = im.resize((w * k, h * k), Image.NEAREST)
    elif max(w, h) > max_size:
        k = max_size / max(w, h)
        im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    if alpha:
        im.save(buf, "PNG")
        mime = "image/png"
    else:
        im.save(buf, "JPEG", quality=88)
        mime = "image/jpeg"
    return {"type": "image", "data": base64.b64encode(buf.getvalue()).decode(), "mimeType": mime}, frames


def result_content(res, show, max_size, notes, preset):
    from PIL import Image

    lines = [f"다 그렸어요: {preset.get('name')} ({res.get('elapsed', '?')}초)"]
    if res.get("seed") is not None:
        lines.append(f"시드: {res['seed']} (같은 그림을 다시 얻으려면 seed 칸에 넣기)")
    lines += [f"참고: {n}" for n in notes]
    lines.append("그림 파일:")
    content, pics = [], []
    items = res.get("images", [])
    # 확인용 그림(뼈대 확인, 잘린 부분 확인 등)은 보여 줄 차례를 뒤로
    order = sorted(range(len(items)), key=lambda i: "확인" in items[i].get("label", ""))
    shown = set(order[:max(0, int(show))])
    for i, item in enumerate(items):
        try:
            path = local_path(item)
        except Exception as e:
            lines.append(f"- {item.get('label')}: (가져오지 못함: {e})")
            continue
        info = ""
        if i in shown:
            try:
                with Image.open(path) as im:
                    info = f" {im.size[0]}x{im.size[1]}"
                    pic, frames = preview(im, max_size)
                    if frames > 1:
                        info += f", 움직이는 그림 {frames}프레임 (첫 프레임만 보여 줌)"
                pics.append((item.get("label"), pic))
            except Exception as e:
                info = f" (미리보기 실패: {e})"
        lines.append(f"- {item.get('label')}{info}: {path}")
    content.append({"type": "text", "text": "\n".join(lines)})
    for label, pic in pics:
        content.append({"type": "text", "text": f"[{label}]"})
        content.append(pic)
    return {"content": content}


# ---------- 일 맡기고 기다리기 ----------

JOBS = {}  # job_id -> {"preset": preset, "notes": [...], "show": n, "max_size": n}


def wait_job(job_id, wait, progress):
    job = JOBS.get(job_id)
    t0 = time.time()
    while True:
        s = api("/api/job/" + job_id)
        st = s.get("status")
        if st == "done":
            return result_content(s, job["show"], job["max_size"], job["notes"], job["preset"]) if job else \
                {"content": [{"type": "text", "text": json.dumps(s, ensure_ascii=False)}]}
        if st == "error":
            return {"content": [{"type": "text", "text": "그리지 못했어요: " + s.get("message", "")}], "isError": True}
        if st == "unknown":
            raise ToolError("그 일을 찾지 못했어요. 그림 도구를 다시 켰다면 처음부터 다시 그려 주세요.")
        if st == "queued":
            msg = f"차례를 기다리는 중 (앞에 {s.get('ahead', 0)}개)"
        else:
            msg = f"그리는 중 {s.get('elapsed', 0)}초" + (f", 프레임 {s['frame']}/{s['frames']}" if s.get("frames", 1) > 1 else "")
        if time.time() - t0 >= wait:
            return {"content": [{"type": "text", "text":
                    f"아직 그리는 중이에요 ({msg}). picapp_job 에 job_id \"{job_id}\" 를 넣어 이어서 기다리세요."}]}
        progress(msg)
        time.sleep(1.5)


def run(args, progress):
    preset = find_preset(str(args.get("feature", "")))
    if preset.get("tool"):
        raise ToolError(f"'{preset.get('name')}' 는 그림 도구 화면에서만 쓰는 도구예요.")
    values, notes = prepare_values(preset, args.get("values") or {})
    ensure_ready(progress)
    r = api("/api/run", {"preset": preset["id"], "values": values}, timeout=120)
    JOBS[r["prompt_id"]] = {"preset": preset, "notes": notes, "show": int(args.get("show", 4)),
                            "max_size": int(args.get("preview_size", 640))}
    return wait_job(r["prompt_id"], float(args.get("wait_seconds", WAIT_DEFAULT)), progress)


def recent(args):
    dirs = [d for d in (comfy_output_dir(), RESULT_DIR) if d and os.path.isdir(d)]
    files = []
    for d in dirs:
        for root, sub, names in os.walk(d):
            if root.count(os.sep) - d.count(os.sep) >= 2:
                sub[:] = []
            for n in names:
                if n.lower().endswith(IMAGE_EXT):
                    p = os.path.join(root, n)
                    files.append((os.path.getmtime(p), p))
    files.sort(reverse=True)
    seen, uniq = set(), []  # 후처리 그림은 두 폴더에 같은 이름으로 있다
    for t, p in files:
        if os.path.basename(p) not in seen:
            seen.add(os.path.basename(p))
            uniq.append((t, p))
    files = uniq
    n = int(args.get("count", 10))
    if not files:
        return text("결과 그림이 아직 없어요." + ("" if dirs else " (결과 폴더를 찾지 못했어요)"))
    lines = [time.strftime("%m-%d %H:%M", time.localtime(t)) + "  " + p for t, p in files[:n]]
    return text("최근 그림 (새것부터):\n" + "\n".join(lines))


def view(args):
    path = args.get("path", "")
    img = open_image(path)
    pic, frames = preview(img, int(args.get("max_size", 1024)))
    info = f"{getattr(img, 'filename', path)}  {img.size[0]}x{img.size[1]}" + \
           (f", {frames}프레임" if frames > 1 else "") + (", 투명 있음" if has_alpha(img) else "")
    return {"content": [{"type": "text", "text": info}, pic]}


def text(s, error=False):
    out = {"content": [{"type": "text", "text": s}]}
    if error:
        out["isError"] = True
    return out


# ---------- MCP 도구 목록 ----------

def tool_list():
    try:
        names = ", ".join(f"{p['id']}={p.get('name')}" for p in load_presets() if not p.get("tool"))
    except OSError:
        names = ""
    return [
        {"name": "picapp_features",
         "title": "그림 도구 기능 목록",
         "description": "그림 도구의 기능(탭)과 각 칸(id, 종류, 기본값, 고를 수 있는 값)을 알려 줘요. "
                        "feature 를 주면 그 기능의 칸을 자세히, 안 주면 전체를 간단히. 저장된 색 팔레트와 LoRA 목록도 함께. "
                        f"지금 기능: {names}",
         "inputSchema": {"type": "object", "properties": {
             "feature": {"type": "string", "description": "기능 id 또는 이름 (비우면 전체 목록)"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "picapp_run",
         "title": "그림 도구로 그리기",
         "description": "그림 도구의 기능 하나를 실행해 그림을 그리고, 결과 그림(미리보기)과 이 컴퓨터의 파일 경로를 돌려줘요. "
                        "칸 값은 picapp_features 로 확인하세요. 안 넣은 칸은 기본값. 그림 도구나 ComfyUI 가 꺼져 있으면 켜요. "
                        "wait_seconds 안에 안 끝나면 job_id 를 돌려주니 picapp_job 으로 이어서 기다리세요.",
         "inputSchema": {"type": "object", "required": ["feature"], "properties": {
             "feature": {"type": "string", "description": "기능 id 또는 이름. 예: 01_character"},
             "values": {"type": "object", "description": "칸 id → 값. 그림 칸은 파일 경로. "
                        "고치기(mask_image) 칸은 {\"image\": 경로, \"boxes\": [[x0,y0,x1,y1]]} (0~1 비율)"},
             "wait_seconds": {"type": "number", "description": f"기다릴 최대 초 (기본 {WAIT_DEFAULT})"},
             "show": {"type": "integer", "description": "미리보기로 보여 줄 그림 수 (기본 4, 0 이면 경로만)"},
             "preview_size": {"type": "integer", "description": "미리보기 가장 긴 쪽 픽셀 (기본 640)"}}}},
        {"name": "picapp_job",
         "title": "그리던 것 이어서 기다리기",
         "description": "picapp_run 이 job_id 를 돌려줬을 때 이어서 기다리고, 끝나면 결과를 돌려줘요.",
         "inputSchema": {"type": "object", "required": ["job_id"], "properties": {
             "job_id": {"type": "string"},
             "wait_seconds": {"type": "number", "description": f"기다릴 최대 초 (기본 {WAIT_DEFAULT})"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "picapp_stop",
         "title": "그리기 멈추기",
         "description": "지금 그리고 있는 것을 멈춰요 (애니메이션이면 남은 프레임도).",
         "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}}},
        {"name": "picapp_recent",
         "title": "최근 그림 찾기",
         "description": "결과 폴더(ComfyUI output, PicApp results)에서 최근 그림 파일 경로를 새것부터 알려 줘요. "
                        "사용자가 그림 도구 화면에서 그린 것도 나와요.",
         "inputSchema": {"type": "object", "properties": {
             "count": {"type": "integer", "description": "몇 개 (기본 10)"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "picapp_view",
         "title": "그림 보기",
         "description": "이 컴퓨터의 그림 파일을 열어 보여 줘요 (크기, 투명 여부 포함). 고칠 곳 상자를 정하기 전에 보세요.",
         "inputSchema": {"type": "object", "required": ["path"], "properties": {
             "path": {"type": "string", "description": "그림 파일 경로"},
             "max_size": {"type": "integer", "description": "가장 긴 쪽 픽셀 (기본 1024)"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "picapp_status",
         "title": "그림 도구 상태",
         "description": "그림 도구와 ComfyUI 가 켜져 있는지 확인하고, 꺼져 있으면 켜요.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "picapp_open_folder",
         "title": "결과 폴더 열기",
         "description": "사용자 화면에 결과 폴더를 탐색기로 열어요.",
         "inputSchema": {"type": "object", "properties": {}}},
    ]


def call(name, args, progress):
    try:
        if name == "picapp_features":
            if args.get("feature"):
                out = describe_preset(find_preset(args["feature"]), True)
            else:
                out = {"features": [describe_preset(p, False) for p in load_presets()]}
            out["field_types"] = TYPE_HELP
            out["palettes"] = [p.get("name") for p in palettes()]
            lr = loras()
            out["loras"] = lr if lr is not None else "그림 도구가 꺼져 있어서 못 읽었어요"
            return text(json.dumps(out, ensure_ascii=False, indent=1 if args.get("feature") else None))
        if name == "picapp_run":
            return run(args, progress)
        if name == "picapp_job":
            return wait_job(args["job_id"], float(args.get("wait_seconds", WAIT_DEFAULT)), progress)
        if name == "picapp_stop":
            api("/api/interrupt", {"id": args.get("job_id") or ""})
            return text("멈췄어요.")
        if name == "picapp_recent":
            return recent(args)
        if name == "picapp_view":
            return view(args)
        if name == "picapp_status":
            st = ensure_ready(progress, need_comfy=False)
            if not st.get("comfy"):
                st = ensure_ready(progress)
            return text(f"그림 도구 켜짐 (판 {st.get('version')}), ComfyUI 연결됨. 화면: {base_url()}")
        if name == "picapp_open_folder":
            ensure_ready(progress, need_comfy=False)
            return text("열었어요: " + api("/api/open-folder", {}).get("path", ""))
        return text(f"모르는 도구: {name}", error=True)
    except ToolError as e:
        return text(str(e), error=True)
    except (urllib.error.URLError, OSError) as e:
        if server_up() is None:
            return text("그림 도구가 꺼져 있어요. picapp_status 로 켜 보세요.", error=True)
        return text(f"오류: {e}", error=True)
