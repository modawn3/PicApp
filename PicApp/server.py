"""그림 도구: ComfyUI를 뒤에서 돌리는 버튼식 프로그램.

표준 라이브러리만 쓴다 (ComfyUI 포터블의 python_embeded 로 바로 실행).
각 기능은 presets/<폴더>/ 안의 workflow_api.json + preset.json 으로 정의된다.
ComfyUI 밖의 후처리는 postprocess/<이름>.py 의 run(image, params) 으로 붙인다.
"""
import base64
import hashlib
import importlib.util
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ComfyUI 포터블의 파이썬(python_embeded)은 이 파일이 있는 폴더를 모듈 찾는 곳에 넣지 않는다
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remote   # 다른 기기에서 접속 (remote.py)
import updater  # 자동 업데이트 (updater.py)

APP_VERSION = "2026-10-30a"  # web/app.js 의 APP_VERSION 과 같아야 한다
APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
PRESET_DIR = os.path.join(APP_DIR, "presets")
POST_DIR = os.path.join(APP_DIR, "postprocess")
RESULT_DIR = os.path.join(APP_DIR, "results")
PALETTE_DIR = os.path.join(APP_DIR, "palettes")
POSE_DIR = os.path.join(APP_DIR, "poses")  # 3D 자세 만들기에서 저장한 자세
ASEPRITE_DIR = os.path.join(APP_DIR, "aseprite")  # Aseprite 빌드 스크립트와 연결용 스크립트

DEFAULT_SETTINGS = {
    "comfy_url": "http://127.0.0.1:8188",
    "comfy_dir": "..\\ComfyUI_windows_portable",
    "comfy_start_bat": "run_nvidia_gpu.bat",
    "port": 8190,
    "open_browser": True,
    "translate_model": "Helsinki-NLP/opus-mt-ko-en",
    "translate_device": "cpu",
    "remote": False,             # 원격접속_설정.bat 으로 켠다
    "remote_allow": "tailscale",  # "lan" 이면 같은 와이파이도
    "update_repo": "modawn3/picapp",  # 업데이트 받을 GitHub 저장소 "아이디/이름"
    "update_branch": "main",
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    path = os.path.join(APP_DIR, "settings.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s.update(json.load(f))
    s["comfy_url"] = s["comfy_url"].rstrip("/")
    if not os.path.isabs(s["comfy_dir"]):
        s["comfy_dir"] = os.path.normpath(os.path.join(APP_DIR, s["comfy_dir"]))
    if not os.path.isdir(s["comfy_dir"]) and os.path.isdir(r"C:\AI-PIC\ComfyUI_windows_portable"):
        s["comfy_dir"] = r"C:\AI-PIC\ComfyUI_windows_portable"
    return s


SETTINGS = load_settings()
CLIENT_ID = uuid.uuid4().hex
JOBS = {}  # prompt_id -> {"preset": id, "seed": n, "started": t, "result": {...}}


# ---------- ComfyUI 와 대화 ----------

class ComfyError(Exception):
    pass


def comfy(path, data=None, headers=None, timeout=30, raw=False):
    url = SETTINGS["comfy_url"] + path
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode("utf-8")
        headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return (body, r.headers.get("Content-Type")) if raw else json.loads(body or b"null")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        raise ComfyError(body)
    except (urllib.error.URLError, OSError) as e:
        raise ComfyError({"error": {"message": "ComfyUI에 연결할 수 없어요. ComfyUI가 켜져 있는지 확인하세요.",
                                    "details": str(e)}})


def comfy_alive():
    try:
        comfy("/system_stats", timeout=3)
        return True
    except ComfyError:
        return False


def upload_png(png_bytes, name):
    boundary = "----picapp" + uuid.uuid4().hex
    parts = []
    for key, val in (("type", "input"), ("subfolder", "picapp"), ("overwrite", "true")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                 f'Content-Type: image/png\r\n\r\n'.encode() + png_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    res = comfy("/upload/image", data=b"".join(parts),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return (res["subfolder"] + "/" if res.get("subfolder") else "") + res["name"]


def output_dir():
    """결과 폴더: ComfyUI 의 output 폴더 (settings.json 의 output_dir 로 바꿀 수 있음)."""
    d = SETTINGS.get("output_dir") or os.path.join(SETTINGS["comfy_dir"], "ComfyUI", "output")
    if not os.path.isabs(d):
        d = os.path.normpath(os.path.join(APP_DIR, d))
    return d if os.path.isdir(d) else None


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ---------- Aseprite 연결 (aseprite/Aseprite_빌드.bat 으로 승진님 PC 에서 빌드한 것) ----------

def find_aseprite():
    """settings.json 의 aseprite_exe, 아니면 빌드 스크립트가 만든 곳, 아니면 스팀/설치판."""
    for c in (SETTINGS.get("aseprite_exe"),
              os.path.join(APP_DIR, "..", "Aseprite", "build", "bin", "aseprite.exe"),
              r"C:\AI-PIC\Aseprite\build\bin\aseprite.exe",
              r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe",
              r"C:\Program Files\Aseprite\Aseprite.exe"):
        if c and os.path.isfile(c):
            return os.path.normpath(c)
    return None


def aseprite_batch(exe, args):
    """화면 없이 Aseprite 를 한 번 돌린다 (-b)."""
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    r = subprocess.run([exe, "-b", *args], capture_output=True, timeout=180, creationflags=flags)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).decode("utf-8", "replace").strip()
        raise RuntimeError("Aseprite 가 처리하지 못했어요. " + msg[-300:])


def result_file(url):
    """결과 카드의 주소 -> PicApp/results 안의 파일. ComfyUI 결과면 results 로 복사한다 (Aseprite 에서 고쳐 저장할 곳)."""
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    os.makedirs(RESULT_DIR, exist_ok=True)
    if u.path == "/api/result":
        path = os.path.join(RESULT_DIR, os.path.basename(q.get("name", "")))
    elif u.path == "/api/image":
        path = os.path.join(RESULT_DIR, os.path.basename(q.get("filename", "")))
        if not os.path.exists(path):
            body, _ = comfy("/view?" + urllib.parse.urlencode(
                {k: q.get(k, "") for k in ("filename", "subfolder", "type")}), raw=True)
            with open(path, "wb") as f:
                f.write(body)
    else:
        raise ValueError("이 그림은 Aseprite 로 열 수 없어요.")
    if not os.path.isfile(path):
        raise ValueError("그림 파일을 찾지 못했어요. 다시 만들어 보세요.")
    return path


def result_url(path):
    return "/api/result?" + urllib.parse.urlencode({"name": os.path.basename(path), "t": int(time.time() * 1000)})


def aseprite_open(url, sheet=None):
    """그림을 Aseprite 로 연다. 스프라이트 시트면 프레임을 나눈 .aseprite 를 만들어 애니메이션으로 연다."""
    exe = find_aseprite()
    if not exe:
        raise ValueError("Aseprite 를 찾지 못했어요. PicApp\\aseprite\\Aseprite_빌드.bat 으로 먼저 빌드하세요.")
    path = result_file(url)
    target = path
    if sheet:
        target = os.path.splitext(path)[0] + ".aseprite"
        if not os.path.exists(target):  # 이미 있으면 Aseprite 에서 고치던 것이니 그대로 연다
            params = {"sheet": path, "out": target, "cw": sheet["cell"][0], "ch": sheet["cell"][1],
                      "count": sheet["count"], "cols": sheet["cols"], "ms": sheet.get("ms", 120)}
            args = []
            for k, v in params.items():
                args += ["--script-param", f"{k}={v}"]
            aseprite_batch(exe, args + ["--script", os.path.join(ASEPRITE_DIR, "sheet_to_anim.lua")])
    subprocess.Popen([exe, target], cwd=os.path.dirname(exe))
    return {"url": result_url(path), "file": target}


def aseprite_import(url, sheet=None):
    """Aseprite 에서 저장한 것을 다시 가져온다. 애니메이션은 .aseprite 를 시트 PNG 로 다시 뽑는다."""
    path = result_file(url)
    if sheet:
        ase = os.path.splitext(path)[0] + ".aseprite"
        exe = find_aseprite()
        if not exe or not os.path.exists(ase):
            raise ValueError("먼저 'Aseprite로 열기' 를 눌러 주세요.")
        aseprite_batch(exe, [ase, "--sheet", path, "--sheet-type", "rows",
                             "--sheet-columns", str(sheet["cols"])])
    return {"url": result_url(path)}


def start_comfy_if_needed():
    if comfy_alive():
        return
    bat = os.path.join(SETTINGS["comfy_dir"], SETTINGS["comfy_start_bat"])
    if os.name == "nt" and os.path.exists(bat):
        print("ComfyUI 를 켜는 중:", bat)
        subprocess.Popen(f'start "ComfyUI" /D "{SETTINGS["comfy_dir"]}" "{SETTINGS["comfy_start_bat"]}"', shell=True)
    else:
        print("ComfyUI 가 꺼져 있어요. 직접 켜 주세요. (찾은 위치:", bat, ")")


# ---------- 한글 → 영어 번역 (인터넷 없이, CPU) ----------
# SD 1.5 는 영어만 알아듣는다. 한글이 들어간 칸은 작은 번역 모델(opus-mt-ko-en, 약 300MB)로 바꾼다.
# ComfyUI 포터블에 이미 있는 transformers 를 쓰므로 따로 설치할 것은 없다. 모델은 처음 한 번만 받는다.

HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
MODEL_DIR = os.path.join(APP_DIR, "models", "translate")
DICT_PATH = os.path.join(APP_DIR, "번역사전.txt")
_mt = {"model": None, "tok": None, "state": "idle", "error": None}
_mt_lock = threading.Lock()
_mt_cache = {}


def has_hangul(text):
    return bool(HANGUL.search(text or ""))


def mt_ready_on_disk():
    return os.path.exists(os.path.join(MODEL_DIR, "받기_완료.txt"))  # 받다가 끊긴 모델은 다시 받는다


def load_dictionary():
    words = {}
    if os.path.exists(DICT_PATH):
        with open(DICT_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0]
                if "=" in line:
                    ko, en = line.split("=", 1)
                    if ko.strip() and en.strip():
                        words[ko.strip()] = en.strip()
    return dict(sorted(words.items(), key=lambda kv: -len(kv[0])))  # 긴 말부터 바꾸기


def _download_model():
    from huggingface_hub import HfApi, snapshot_download

    files = HfApi().list_repo_files(SETTINGS["translate_model"])
    weights = ["model.safetensors"] if "model.safetensors" in files else ["pytorch_model.bin"]
    snapshot_download(SETTINGS["translate_model"], local_dir=MODEL_DIR,
                      allow_patterns=["*.json", "*.spm"] + weights)
    with open(os.path.join(MODEL_DIR, "받기_완료.txt"), "w", encoding="utf-8") as f:
        f.write(SETTINGS["translate_model"])


def _load_mt():
    with _mt_lock:
        if _mt["model"] is not None:
            return
        try:
            if not mt_ready_on_disk():
                _mt["state"] = "downloading"
                print("번역 모델을 처음 받는 중 (약 300MB, 한 번만)…")
                _download_model()
            _mt["state"] = "loading"
            from transformers import MarianMTModel, MarianTokenizer

            _mt["tok"] = MarianTokenizer.from_pretrained(MODEL_DIR)
            _mt["model"] = MarianMTModel.from_pretrained(MODEL_DIR).to(SETTINGS["translate_device"]).eval()
            _mt["state"], _mt["error"] = "ready", None
        except Exception as e:
            _mt["state"], _mt["error"] = "error", f"{type(e).__name__}: {e}"
            raise RuntimeError("번역 모델을 준비하지 못했어요. 처음 한 번은 인터넷이 필요해요.\n" + _mt["error"])


def _machine_translate(texts):
    import torch

    _load_mt()
    tok, model = _mt["tok"], _mt["model"]
    with _mt_lock, torch.no_grad():
        batch = tok(texts, return_tensors="pt", padding=True, truncation=True).to(model.device)
        out = model.generate(**batch, num_beams=4, max_new_tokens=160)
    return [tok.decode(o, skip_special_tokens=True) for o in out]


def _tidy(en):
    en = en.strip().rstrip(".").strip()
    if len(en) > 1 and en[0].isupper() and en[1].islower():
        en = en[0].lower() + en[1:]
    return en


# 쉼표, 문장 끝(. ), 줄바꿈, 괄호, 강조 숫자(:1.2)는 그대로 두고 그 사이의 말만 바꾼다: "(갈색 모자:1.2)" → "(brown hat:1.2)"
_SEP = re.compile(r"(\s*[,()\[\]]\s*|:\s*[\d.]+\s*(?=[)\]])|[.!?。]\s+|[.!?。]$|\n+)")


def translate_prompt(text, translator=None):
    """한글이 있는 조각만 번역. 영어 조각과 강조 문법은 그대로."""
    if not has_hangul(text):
        return text
    translator = translator or _machine_translate
    words = load_dictionary()
    parts = _SEP.split(text)
    for i in range(0, len(parts), 2):  # 짝수 칸 = 말, 홀수 칸 = 구분 기호
        core = parts[i].strip()
        if not has_hangul(core):
            continue
        if core in words:
            parts[i] = words[core]
            continue
        for ko, en in words.items():
            core = core.replace(ko, en)
        parts[i] = core
    todo = [p for p in parts[0::2] if has_hangul(p) and p not in _mt_cache]
    todo = list(dict.fromkeys(todo))
    if todo:
        for k, v in zip(todo, translator(todo)):
            _mt_cache[k] = _tidy(v)
    for i in range(0, len(parts), 2):
        if has_hangul(parts[i]):
            parts[i] = _mt_cache[parts[i]]
    return "".join(parts)


# ---------- 프리셋 ----------

def load_presets():
    presets = []
    for folder in sorted(os.listdir(PRESET_DIR)):
        cfg_path = os.path.join(PRESET_DIR, folder, "preset.json")
        if not os.path.exists(cfg_path):
            continue
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["id"] = folder
        presets.append(cfg)
    return presets


def get_preset(pid):
    for p in load_presets():
        if p["id"] == pid:
            return p
    raise KeyError(pid)


def load_workflow(preset):
    with open(os.path.join(PRESET_DIR, preset["id"], preset.get("workflow", "workflow_api.json")), encoding="utf-8") as f:
        return json.load(f)


def set_input(wf, node, name, value):
    if node not in wf:
        raise ValueError(f"워크플로에 노드 {node} 가 없어요 (preset.json 확인)")
    wf[node]["inputs"][name] = value


def bypass_node(wf, node, through):
    """ComfyUI 의 '건너뛰기'와 같다: node 를 쓰던 곳이 node 의 through 입력을 바로 쓰게 하고 node 를 지운다.
    출력이 여러 개면 through 를 {"0": "positive", "1": "negative"} 처럼 출력 번호별로 준다."""
    if node not in wf:
        return
    by_slot = through if isinstance(through, dict) else {"0": through}
    for n in wf.values():
        for k, v in n["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and str(v[0]) == node:
                n["inputs"][k] = wf[node]["inputs"][by_slot[str(v[1])]]
    del wf[node]


def prune(wf):
    """저장/미리보기 노드에서 닿지 않는 노드를 지운다 (꺼 둔 기능의 확장 노드가 없어도 되게)."""
    keep, todo = set(), [n for n, v in wf.items() if v["class_type"] in ("SaveImage", "PreviewImage")]
    while todo:
        n = todo.pop()
        if n in keep or n not in wf:
            continue
        keep.add(n)
        todo += [str(v[0]) for v in wf[n]["inputs"].values() if isinstance(v, list) and len(v) == 2]
    for n in list(wf):
        if n not in keep:
            del wf[n]


_node_ok = {}


def missing_nodes(classes):
    out = []
    for c in classes:
        if not _node_ok.get(c):  # 있는 것만 기억 (ComfyUI 를 다시 켜서 설치하면 바로 알아채게)
            _node_ok[c] = bool(comfy(f"/object_info/{urllib.parse.quote(c)}"))
        if not _node_ok[c]:
            out.append(c)
    return out


def decode_data_url(url):
    return base64.b64decode(url.split(",", 1)[1])


def combine_mask(val):
    """브라우저에서 칠한 마스크를 ComfyUI 형식으로: 칠한 곳 = 투명(알파 0).

    색은 원본 그대로 두고 알파만 바꾼다 (브라우저 캔버스로 하면 투명한 곳의 색이 검게 지워진다).
    """
    from PIL import Image

    img = Image.open(io.BytesIO(decode_data_url(val["image"]))).convert("RGB")
    if not val.get("mask"):
        raise ValueError("고칠 곳을 붓으로 칠해 주세요.")
    mask = Image.open(io.BytesIO(decode_data_url(val["mask"]))).convert("RGBA").getchannel("A")
    if mask.size != img.size:
        mask = mask.resize(img.size)
    if mask.getbbox() is None:
        raise ValueError("고칠 곳을 붓으로 칠해 주세요.")
    out = img.convert("RGBA")
    out.putalpha(mask.point(lambda a: 0 if a > 0 else 255))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def list_loras():
    """ComfyUI\\models\\loras 안의 파일 이름 (ComfyUI 가 알려 주는 목록)."""
    info = comfy("/object_info/LoraLoader").get("LoraLoader", {})
    opt = info.get("input", {}).get("required", {}).get("lora_name", [[]])
    if opt and opt[0] == "COMBO":
        return opt[1].get("options", [])
    return opt[0] if opt and isinstance(opt[0], list) else []


def lora_word(name):
    """파일 이름에서 단어를 뽑는다 (학습 노트는 이 단어로 캐릭터를 부르게 학습한다)."""
    return os.path.splitext(os.path.basename(name.replace("\\", "/")))[0]


def apply_loras(wf, items):
    """체크포인트와 그 모델·CLIP 을 쓰는 노드 사이에 LoraLoader 를 줄줄이 끼운다."""
    ck = next((n for n, v in wf.items() if v["class_type"] == "CheckpointLoaderSimple"), None)
    if ck is None or not items:
        return
    model, clip, ids = [ck, 0], [ck, 1], []
    for k, x in enumerate(items):
        nid = f"lora{k + 1}"
        s = float(x.get("strength", 0.8))
        wf[nid] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip, "lora_name": x["name"],
                                                          "strength_model": s, "strength_clip": s}}
        model, clip = [nid, 0], [nid, 1]
        ids.append(nid)
    for n, v in wf.items():
        if n in ids:
            continue
        for key, val in v["inputs"].items():
            if val == [ck, 0]:
                v["inputs"][key] = list(model)
            elif val == [ck, 1]:
                v["inputs"][key] = list(clip)


def check_requires(f):
    miss = missing_nodes(f["requires"])
    if miss:
        raise ValueError(f"'{f['label']}' 에 필요한 확장 노드가 ComfyUI 에 없어요: {', '.join(miss)}\n"
                         f"설치 안내의 '{f.get('setup', '얼굴·손 자동 다듬기 준비')}'를 따라 설치하거나, "
                         + ("이 칸을 비우고 그리세요." if f["type"] in ("image", "images") else "이 칸을 끄고 그리세요."))


def build_prompt(preset, values, seed=None):
    """preset.json 의 fields 설정대로 입력값을 워크플로에 채운다.
    seed: 여러 장을 한 번에 그릴 때 첫 장의 시드를 나머지에도 쓰려고 넘긴다."""
    wf = load_workflow(preset)
    seed_used = None
    remove = []  # 선택에 따라 지울 노드
    values = dict(values)
    for f in preset["fields"]:  # 화면에서 번역이 안 끝났을 때를 위한 안전장치
        if f["type"] in ("text", "textarea") and f.get("translate", True) and has_hangul(values.get(f["id"])):
            values[f["id"]] = translate_prompt(values[f["id"]])
    text_values = {f["id"]: values.get(f["id"], f.get("default", "")) for f in preset["fields"]}
    job_values = {}  # 후처리에서 다시 쓸 값 (팔레트 등)
    bypass = []  # 꺼 둔 단계
    add_text = []  # 켜 둔 칸이 프롬프트 끝에 붙이는 말 (예: 캐릭터만 그리기)
    for f in preset["fields"]:
        fid, ftype = f["id"], f["type"]
        val = values.get(fid, f.get("default"))
        if ftype not in ("image", "mask_image", "images"):
            job_values[fid] = val  # 후처리에서 칸 값을 다시 쓸 수 있게
        if ftype in ("image", "mask_image", "images"):  # images 는 /api/run 에서 한 장씩 나눠서 온다
            if not val:
                if f.get("required", True):
                    raise ValueError(f"'{f['label']}' 그림을 올려 주세요.")
                bypass += f.get("bypass_empty", [])  # 안 올리면 그 기능을 건너뛴다 (예: 캐릭터 참고)
                continue
            if f.get("requires"):
                check_requires(f)
            if ftype == "mask_image":
                png = combine_mask(val)
            else:
                png = decode_data_url(val)
            # 내용으로 이름을 지어서 애니메이션처럼 같은 그림을 여러 번 보내도 한 번만 쌓이게
            val = upload_png(png, f"{preset['id']}_{fid}_{hashlib.sha1(png).hexdigest()[:12]}.png")
        elif ftype == "seed":
            if seed is not None:
                val = seed
            elif val in (None, "", -1, "-1"):
                val = random.randint(0, 2**32 - 1)
            val = int(val)
            seed_used = val
        elif ftype == "number":
            val = float(val) if "." in str(f.get("step", 1)) else int(float(val))
        elif ftype == "palette":
            if val and val.get("colors") and val.get("guide", True):
                words = color_phrase(val["colors"])
                for t in f.get("targets", []):
                    if words and t.get("append"):
                        set_input(wf, t["node"], t["input"], f'{wf[t["node"]]["inputs"][t["input"]]}, {words}')
            job_values[fid] = val
            continue
        elif ftype == "loras":
            items = [x for x in (val or []) if isinstance(x, dict) and x.get("name")]
            apply_loras(wf, items)
            words = ", ".join(lora_word(x["name"]) for x in items if x.get("word", True))
            for t in f.get("prompt_targets", []):
                if words and t["node"] in wf:
                    set_input(wf, t["node"], t["input"], f'{wf[t["node"]]["inputs"][t["input"]]}, {words}')
            job_values[fid] = items
            continue
        elif ftype == "toggle":
            on = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "on")
            if on and f.get("requires"):
                check_requires(f)
            bypass += f.get("bypass_on" if on else "bypass_off", [])
            if on:
                add_text += f.get("add_text", [])
            continue
        elif ftype == "choice":
            opt = next((o for o in f["options"] if o["value"] == val), f["options"][0])
            for t in opt.get("set", []):
                set_input(wf, t["node"], t["input"], t["value"])
            remove += opt.get("remove", [])
            continue
        for t in f.get("targets", []):
            v = t["template"].format(**text_values) if "template" in t else val
            set_input(wf, t["node"], t["input"], v)
    for t in add_text:  # 글자 칸을 다 채운 뒤에 붙인다
        if t["node"] in wf:
            set_input(wf, t["node"], t["input"], f'{wf[t["node"]]["inputs"][t["input"]]}, {t["text"]}')
    for b in bypass:
        bypass_node(wf, b["node"], b["input"])
    for n in remove:
        wf.pop(n, None)
    prune(wf)
    return wf, seed_used, job_values


# ---------- 색 팔레트 ----------
# 그릴 때: 팔레트 색을 영어 색 이름으로 바꿔 프롬프트 끝에 붙인다 (분위기만 따라감).
# 그린 뒤: postprocess/palette.py 가 모든 색을 팔레트 색으로 맞춘다 (정확함).

COLOR_NAMES = {
    "black": (20, 20, 20), "white": (250, 250, 250), "gray": (128, 128, 128), "silver": (192, 192, 200),
    "red": (200, 30, 30), "crimson": (150, 20, 40), "maroon": (110, 25, 30), "pink": (240, 150, 180),
    "orange": (240, 130, 30), "copper": (184, 100, 50), "rust": (160, 70, 30), "brown": (110, 70, 40),
    "dark brown": (60, 40, 25), "tan": (200, 160, 110), "beige": (230, 215, 180), "cream": (245, 235, 205),
    "gold": (212, 175, 55), "brass": (181, 140, 60), "yellow": (240, 220, 40), "olive": (120, 120, 40),
    "lime green": (150, 210, 60), "green": (50, 150, 60), "forest green": (40, 90, 50), "teal": (40, 140, 140),
    "turquoise": (60, 200, 200), "sky blue": (130, 190, 235), "blue": (40, 80, 200), "navy blue": (25, 35, 90),
    "purple": (110, 50, 160), "violet": (150, 100, 210), "lavender": (190, 170, 225), "magenta": (200, 40, 160),
}


def hex_to_rgb(hx):
    hx = hx.lstrip("#")
    return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))


def color_phrase(colors, limit=5):
    """['#b5893b', ...] -> 'brass, copper and teal color scheme'. 선·하이라이트용 어둡거나 밝은 색과 무채색은 뺀다."""
    names = []
    for hx in colors:
        r, g, b = hex_to_rgb(hx)
        light = (max(r, g, b) + min(r, g, b)) / 510
        if light < 0.12 or light > 0.93:
            continue
        name = min(COLOR_NAMES, key=lambda n: (2 * (r - COLOR_NAMES[n][0]) ** 2 + 4 * (g - COLOR_NAMES[n][1]) ** 2
                                               + 3 * (b - COLOR_NAMES[n][2]) ** 2))
        if name not in names and name not in ("black", "white", "gray", "silver"):
            names.append(name)
    names = names[:limit]
    if not names:
        return ""
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{joined} color scheme"


def load_palettes():
    out = []
    if os.path.isdir(PALETTE_DIR):
        for fn in sorted(os.listdir(PALETTE_DIR)):
            if fn.endswith(".json"):
                with open(os.path.join(PALETTE_DIR, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
    return out


def save_palette(name, colors):
    name = name.strip()
    if not name or not colors:
        raise ValueError("팔레트 이름과 색이 필요해요.")
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    os.makedirs(PALETTE_DIR, exist_ok=True)
    with open(os.path.join(PALETTE_DIR, safe + ".json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "colors": colors}, f, ensure_ascii=False, indent=1)


def load_poses():
    out = []
    if os.path.isdir(POSE_DIR):
        for fn in sorted(os.listdir(POSE_DIR)):
            if fn.endswith(".json"):
                with open(os.path.join(POSE_DIR, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
    return out


def save_pose(name, joints):
    name = name.strip()
    if not name or not isinstance(joints, list) or len(joints) != 18:
        raise ValueError("자세 이름과 관절 18개가 필요해요.")
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    os.makedirs(POSE_DIR, exist_ok=True)
    with open(os.path.join(POSE_DIR, safe + ".json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "joints": [[round(float(v), 4) for v in j] for j in joints]}, f, ensure_ascii=False)


def extract_palette(data_url, count):
    """그림에서 많이 쓰인 색 count 개를 뽑는다 (투명한 곳은 뺌)."""
    from PIL import Image

    img = Image.open(io.BytesIO(decode_data_url(data_url))).convert("RGBA")
    img.thumbnail((256, 256), Image.Resampling.NEAREST)  # 섞인 중간색이 생기지 않게
    px = [p[:3] for p in img.getdata() if p[3] > 128]
    if not px:
        raise ValueError("색을 뽑을 곳이 없어요.")
    count = max(2, min(32, int(count)))
    flat = Image.new("RGB", (len(px), 1))
    flat.putdata(px)
    exact = flat.getcolors(count)  # 색 수가 적은 그림은 그대로
    if exact:
        return ["#%02x%02x%02x" % c for _, c in sorted(exact, reverse=True)]
    q = flat.quantize(colors=count, method=Image.Quantize.MEDIANCUT, kmeans=8)
    pal = q.getpalette()
    used = sorted(q.getcolors(), reverse=True)
    return ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _, i in used]


# ---------- 후처리 (ComfyUI 밖에서 하는 일: 도트 변환, 스프라이트 시트 등) ----------

def run_postprocess(step, images, params):
    """images: [(PIL.Image, filename)] -> [(PIL.Image, filename)]"""
    path = os.path.join(POST_DIR, step["step"] + ".py")
    spec = importlib.util.spec_from_file_location("pp_" + step["step"], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run(images, params)


def collect_result(job, hists):
    """hists: 프롬프트마다의 ComfyUI 기록 (애니메이션은 프레임마다 하나, 순서대로)."""
    from PIL import Image  # ComfyUI 포터블에 들어 있음, 후처리에서만 필요

    preset = get_preset(job["preset"])
    many = len(hists) > 1
    result = []
    by_node = {}
    out_cfg = {o["node"]: o for o in preset.get("outputs", [])}
    for o in preset.get("outputs", []):
        by_node[o["node"]] = []
        for k, hist in enumerate(hists):
            imgs = hist.get("outputs", {}).get(o["node"], {}).get("images", [])
            by_node[o["node"]] += imgs
            for im in ([] if o.get("hidden") else imgs):  # hidden: 후처리 재료로만 쓰고 결과 칸에는 안 보임
                q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                            "type": im.get("type", "output")})
                result.append({"label": o["label"] + (f" {k + 1}" if many else ""), "url": "/api/image?" + q,
                               "filename": im["filename"], "send": o.get("send", True), "temp": im.get("type") == "temp"})
    extra = []
    for step in preset.get("postprocess", []):
        params = dict(step.get("params", {}))
        if "params_from" in step:  # 화면의 칸 값으로 켜고 끄는 후처리 (예: 팔레트 맞추기)
            v = job.get("values", {}).get(step["params_from"])
            if not v or not v.get(step.get("enabled_key", "snap"), True):
                continue
            params.update(v)
        if "enabled_by" in step and not job.get("values", {}).get(step["enabled_by"]):
            continue
        for fid in step.get("fields", []):  # 칸 값들을 params 로 (예: 도트 크기, 색 수)
            params[fid] = job.get("values", {}).get(fid)
        nodes = step["from_node"] if isinstance(step["from_node"], list) else [step["from_node"]]
        os.makedirs(RESULT_DIR, exist_ok=True)
        for node in nodes:
            src = []
            for im in by_node.get(node, []):
                body, _ = comfy("/view?" + urllib.parse.urlencode(
                    {"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": im.get("type", "output")}),
                    raw=True)
                src.append((Image.open(io.BytesIO(body)), im["filename"]))
            if not src:
                continue
            label = step["label"] + (f": {out_cfg[node]['label']}" if len(nodes) > 1 and node in out_cfg else "")
            send = step.get("send", out_cfg.get(node, {}).get("send", True))
            for item in run_postprocess(step, src, params):
                img, name = item[0], item[1]
                tag = item[2] if len(item) > 2 else ""  # 한 그림에서 결과가 여러 장이면 구별 이름
                opts = item[3] if len(item) > 3 else {}  # 예: {"ext": "gif", "duration": 120} (움직이는 그림)
                ext = opts.get("ext", "png")
                out = f"{os.path.splitext(name)[0]}_{step['step']}{'_' + str(len(extra)) if tag else ''}.{ext}"
                targets = [os.path.join(RESULT_DIR, out)]
                if output_dir():  # 결과 폴더 한 곳에서 다 보이게 ComfyUI output 에도 저장
                    targets.append(os.path.join(output_dir(), out))
                for t in targets:
                    if ext == "gif":
                        frames = opts["frames"]
                        frames[0].save(t, save_all=True, append_images=frames[1:], duration=opts.get("duration", 120),
                                       loop=0, disposal=2)
                    else:
                        img.save(t)
                extra.append({"label": label + (f" ({tag})" if tag else ""), "url": "/api/result?" + urllib.parse.urlencode({"name": out}),
                              "filename": out, "send": send and ext == "png", "temp": False,
                              "sheet": opts.get("sheet")})  # 스프라이트 시트: Aseprite 에서 프레임으로 나눠 연다
    return extra + result  # 후처리 결과를 앞에


def _prompt_error(hist):
    st = hist.get("status", {})
    if st.get("status_str") == "error":
        msg = "ComfyUI 에서 오류가 났어요."
        for m in st.get("messages", []):
            if m[0] == "execution_error":
                d = m[1]
                msg = f"{d.get('node_type', '')} (노드 {d.get('node_id', '')}): {d.get('exception_message', '').strip()}"
                if "IPAdapter" in d.get("node_type", ""):
                    msg += "\n설치 안내의 '캐릭터 닮게 그리기 준비'에 적힌 모델 파일 두 개의 이름과 폴더를 확인하세요."
                elif "Loader" in d.get("node_type", ""):
                    msg += "\n모델 파일이 없거나 깨졌을 수 있어요. ComfyUI\\models 폴더를 확인하세요."
                elif "out of memory" in msg.lower():
                    msg += "\n그래픽 메모리가 부족해요. 다른 프로그램을 닫고 다시 해 보세요."
        return msg
    if "execution_interrupted" in [m[0] for m in st.get("messages", [])]:
        return "중지했어요."
    return None


def _prompt_done(hist):
    st = hist.get("status", {})
    return st.get("status_str") == "success" or st.get("completed")


def job_status(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return {"status": "unknown"}
    if "result" in job:
        return job["result"]
    pids = job["prompts"]
    hists, q = [], None
    for pid in pids:
        hist = comfy(f"/history/{pid}").get(pid)
        if hist is not None:
            err = _prompt_error(hist)
            if err:
                if len(pids) > 1:  # 남은 프레임은 그릴 필요가 없다
                    comfy("/queue", {"delete": pids})
                job["result"] = {"status": "error", "message": err + (f" (프레임 {len(hists) + 1})" if len(pids) > 1 and err != "중지했어요." else "")}
                return job["result"]
            if _prompt_done(hist):
                hists.append(hist)
                continue
        if q is None:
            q = comfy("/queue")
        running = any(item[1] == pid for item in q.get("queue_running", []))
        pending = any(item[1] == pid for item in q.get("queue_pending", []))
        if hist is None and not running and not pending:  # 줄에서 지워짐 (중지)
            job["result"] = {"status": "error", "message": "중지했어요."}
            return job["result"]
        ahead = sum(1 for item in q.get("queue_pending", []) if item[1] not in pids)
        started = running or hist is not None or len(hists) > 0
        return {"status": "running" if started else "queued", "ahead": 0 if started else ahead,
                "elapsed": round(time.time() - job["started"]),
                "frame": len(hists) + 1, "frames": len(pids)}
    try:
        res = {"status": "done", "images": collect_result(job, hists), "seed": job["seed"],
               "elapsed": round(time.time() - job["started"])}
    except Exception as e:  # 후처리 오류는 그림 생성과 따로 알려 준다
        res = {"status": "error", "message": f"후처리 중 오류: {e}"}
    job["result"] = res
    return res


def friendly_comfy_error(err):
    """ComfyUI 의 /prompt 검사 오류를 사람이 읽을 문장으로."""
    if not isinstance(err, dict):
        return str(err)
    lines = []
    e = err.get("error")
    if isinstance(e, dict):
        lines.append(e.get("message", ""))
    for nid, ne in (err.get("node_errors") or {}).items():
        for x in ne.get("errors", []):
            lines.append(f"- {ne.get('class_type', '')} (노드 {nid}): {x.get('message', '')} {x.get('details', '')}")
    if any("not in list" in l or "value_not_in_list" in l for l in lines):
        lines.append("모델 파일 이름이 다르거나 아직 설치되지 않았을 수 있어요.")
        if any("XL" in l for l in lines):
            lines.append("SDXL 모델은 설치 안내의 'SDXL 모델 준비'를 따라 받아 주세요.")
    if any("does not exist" in l or "class_type" in l.lower() for l in lines):
        lines.append("필요한 확장 노드가 설치돼 있는지 확인하세요.")
    return "\n".join(l for l in lines if l.strip())


# ---------- 웹 서버 ----------

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if not remote.gate(self, SETTINGS, u.path):
            return
        q = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path in ("/", "/index.html"):
                return self.static("index.html")
            if u.path.startswith("/web/"):
                return self.static(u.path[5:])
            if u.path == "/api/presets":
                return self.send(200, load_presets())
            if u.path == "/api/translate/status":
                return self.send(200, {"state": "ready" if _mt["model"] else
                                       ("on_disk" if mt_ready_on_disk() and _mt["state"] == "idle" else _mt["state"]),
                                       "error": _mt["error"]})
            if u.path == "/api/palettes":
                return self.send(200, load_palettes())
            if u.path == "/api/poses":
                return self.send(200, load_poses())
            if u.path == "/api/loras":
                return self.send(200, list_loras())
            if u.path == "/api/status":
                return self.send(200, {"comfy": comfy_alive(), "comfy_url": SETTINGS["comfy_url"], "version": APP_VERSION,
                                       "remote": remote.is_remote(self), "update": updater.configured(),
                                       "aseprite": bool(find_aseprite())})
            if u.path == "/api/update/check":
                try:
                    return self.send(200, updater.check())
                except updater.UpdateError as e:
                    return self.send(200, {"configured": True, "available": False, "error": str(e)})
            if u.path.startswith("/api/job/"):
                return self.send(200, job_status(u.path.rsplit("/", 1)[1]))
            if u.path == "/api/image":
                body, ctype = comfy("/view?" + u.query, raw=True)
                return self.send(200, body, ctype or "image/png")
            if u.path == "/api/result":
                name = os.path.basename(q.get("name", ""))
                with open(os.path.join(RESULT_DIR, name), "rb") as f:
                    return self.send(200, f.read(), "image/gif" if name.endswith(".gif") else "image/png")
            self.send(404, {"error": "없는 주소"})
        except ComfyError as e:
            self.send(502, {"error": friendly_comfy_error(e.args[0])})
        except Exception as e:
            self.send(500, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not remote.gate(self, SETTINGS, u.path):
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            if u.path == "/api/run":
                preset = get_preset(data["preset"])
                values = data.get("values", {})
                rep = preset.get("repeat_over")  # 애니메이션: 그림마다 한 번씩, 같은 시드로
                if rep:
                    frames = values.get(rep) or []
                    if not frames:
                        f = next(f for f in preset["fields"] if f["id"] == rep)
                        raise ValueError(f"'{f['label']}' 그림을 한 장 이상 올려 주세요.")
                    if len(frames) > 24:
                        raise ValueError("프레임은 24장까지 돼요.")
                    builds, seed = [], None
                    for fr in frames:
                        wf, seed, job_values = build_prompt(preset, {**values, rep: fr}, seed)
                        builds.append(wf)
                else:
                    wf, seed, job_values = build_prompt(preset, values)
                    builds = [wf]
                pids = [comfy("/prompt", {"prompt": wf, "client_id": CLIENT_ID})["prompt_id"] for wf in builds]
                JOBS[pids[0]] = {"preset": preset["id"], "seed": seed, "values": job_values, "started": time.time(),
                                 "prompts": pids}
                return self.send(200, {"prompt_id": pids[0], "seed": seed})
            if u.path == "/api/translate":
                try:
                    return self.send(200, {"english": translate_prompt(data.get("text", ""))})
                except RuntimeError as e:
                    return self.send(503, {"error": str(e)})
            if u.path == "/api/palettes":
                save_palette(data.get("name", ""), data.get("colors", []))
                return self.send(200, load_palettes())
            if u.path == "/api/poses":
                save_pose(data.get("name", ""), data.get("joints"))
                return self.send(200, load_poses())
            if u.path == "/api/palette/extract":
                return self.send(200, {"colors": extract_palette(data["image"], data.get("count", 12))})
            if u.path == "/api/open-folder":
                path = output_dir() or RESULT_DIR
                os.makedirs(path, exist_ok=True)
                open_folder(path)
                return self.send(200, {"path": path})
            if u.path == "/api/aseprite/open":
                return self.send(200, aseprite_open(data["url"], data.get("sheet")))
            if u.path == "/api/aseprite/import":
                return self.send(200, aseprite_import(data["url"], data.get("sheet")))
            if u.path == "/api/update/apply":
                try:
                    r = updater.apply()
                except updater.UpdateError as e:
                    return self.send(400, {"error": str(e)})
                r["restart"] = bool(r["changed"])
                if r["restart"]:  # 응답을 보낸 뒤 새 판으로 다시 켠다
                    threading.Timer(0.5, restart).start()
                return self.send(200, r)
            if u.path == "/api/interrupt":
                job = JOBS.get(data.get("id") or "")
                if job and len(job["prompts"]) > 1:  # 아직 차례가 안 온 프레임도 지운다
                    comfy("/queue", {"delete": job["prompts"]})
                comfy("/interrupt", {})
                return self.send(200, {"ok": True})
            self.send(404, {"error": "없는 주소"})
        except ComfyError as e:
            self.send(400, {"error": friendly_comfy_error(e.args[0])})
        except (ValueError, KeyError, RuntimeError) as e:
            self.send(400, {"error": str(e)})
        except subprocess.TimeoutExpired:
            self.send(500, {"error": "Aseprite 가 너무 오래 걸려서 멈췄어요."})
        except Exception as e:
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def static(self, rel):
        path = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not path.startswith(WEB_DIR) or not os.path.isfile(path):
            return self.send(404, {"error": "없는 파일"})
        with open(path, "rb") as f:
            self.send(200, f.read(), MIME.get(os.path.splitext(path)[1], "application/octet-stream"))


_server = {}


def restart():
    _server["restart"] = True
    _server["httpd"].shutdown()


def main():
    port = int(SETTINGS["port"])
    start_comfy_if_needed()
    url = f"http://127.0.0.1:{port}"
    try:
        server = ThreadingHTTPServer((remote.bind_host(SETTINGS), port), Handler)
    except OSError:
        print(f"그림 도구가 이미 켜져 있는 것 같아요. 브라우저에서 {url} 을 여세요.")
        webbrowser.open(url)
        return
    print(f"그림 도구가 켜졌어요: {url}")
    print("이 창을 닫으면 프로그램이 꺼져요. (ComfyUI 창은 따로 닫으세요)")
    remote.print_addresses(SETTINGS, port)
    _server["httpd"] = server
    if SETTINGS.get("open_browser", True) and "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    if _server.get("restart"):
        print("업데이트한 새 판으로 다시 켜는 중...")
        sys.exit(subprocess.call([sys.executable, "-s", os.path.abspath(__file__), "--no-browser"]))


if __name__ == "__main__":
    main()
