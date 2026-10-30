"""LoRA_학습_Colab.ipynb 를 만든다. 셀 코드는 일반 파이썬(셸 명령은 run() 으로)이라 밖에서도 시험할 수 있다."""
import json, sys

cells = []
def md(text): cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n")})
def code(text, title=None):
    meta = {"cellView": "form"} if "#@param" in text or "#@title" in text else {}
    cells.append({"cell_type": "code", "metadata": meta, "execution_count": None, "outputs": [], "source": text.strip("\n")})

md("""
# LoRA 학습 (Colab 무료 GPU)

그림 20~50장으로 **캐릭터 LoRA** 나 **그림체 LoRA** 를 만들어요. 결과는 `이름.safetensors` 파일 하나예요.

**처음 한 번**
1. 위 메뉴 **런타임 → 런타임 유형 변경 → T4 GPU** 를 고르고 저장해요.
2. 구글 드라이브의 `내 드라이브` 에 `LoRA학습` 폴더를 만들고, 그 안에 LoRA 이름과 같은 폴더(예: `steamgirl`)를 만들어 그림을 넣어요.

**매번**
1. 아래 **1. 설정** 칸에 이름과 종류를 고르고
2. 메뉴 **런타임 → 모두 실행**. 구글 드라이브 연결을 물으면 허용해요.
3. 30분~1시간 뒤 결과가 `내 드라이브/LoRA학습/결과/이름/` 에 생기고, 마지막 칸에서 바로 받을 수도 있어요.

**그림 고르는 법**
- 직접 그린 그림, CC0 그림, AI 학습을 허락한 구매 에셋만 쓰세요. 그림 도구로 만든 그림도 돼요.
- 캐릭터: 같은 캐릭터를 여러 자세·각도·표정으로 20~40장. 옷과 색이 일정해야 해요. 배경은 단순할수록 좋아요 (투명 PNG 도 돼요, 흰색으로 채워요).
- 그림체: 그 그림체의 여러 대상(사람, 건물, 소품)을 30~50장. 한 대상만 많으면 그 대상까지 배워요.
- 그림 옆에 같은 이름의 `.txt` (예: `01.png` 와 `01.txt`) 가 있으면 그 설명을 쓰고, 없으면 자동으로 붙여요.

무료 Colab 은 오래 쓰면 끊길 수 있어요. 2바퀴마다 중간 결과를 드라이브에 저장하니, 끊기면 그것을 써도 돼요.
""")

code(r'''
#@title 1. 설정
#@markdown **LoRA 이름**: 영어 소문자·숫자로 (예: steamgirl, wizardstyle). 이 이름이 그림을 부르는 단어가 돼요. 드라이브 폴더 이름과 같아야 해요.
LORA_NAME = "steamgirl"  #@param {type:"string"}
#@markdown **종류**: 캐릭터 하나를 배우면 '캐릭터', 그림 느낌을 배우면 '그림체'
KIND = "캐릭터"  #@param ["캐릭터", "그림체"]
#@markdown 드라이브 안 폴더 (그림은 `내 드라이브/이 폴더/LoRA 이름/` 에)
DRIVE_FOLDER = "LoRA학습"  #@param {type:"string"}
#@markdown 바탕 모델 (그림 도구가 쓰는 DreamShaper 8). 바꾸지 않아도 돼요.
BASE_MODEL = "Lykon/dreamshaper-8"  #@param {type:"string"}
#@markdown 그림 설명 자동으로 붙이기 (.txt 가 없는 그림만)
AUTO_CAPTION = True  #@param {type:"boolean"}
#@markdown 몇 바퀴 배울지 (0 = 알아서: 캐릭터 10, 그림체 15)
EPOCHS = 0  #@param {type:"integer"}

import re
LORA_NAME = LORA_NAME.strip().lower()
assert re.fullmatch(r"[a-z][a-z0-9_]{2,30}", LORA_NAME), "LoRA 이름은 영어 소문자로 시작하고 영어 소문자·숫자·_ 만 3~31글자로 써 주세요."
CHARACTER = KIND == "캐릭터"
if not EPOCHS:
    EPOCHS = 10 if CHARACTER else 15
print(f"이름: {LORA_NAME} / 종류: {KIND} / {EPOCHS}바퀴")
''')

code(r'''
#@title 2. 준비 (학습 프로그램 설치, 몇 분 걸려요)
import os, subprocess, sys

def run(cmd, cwd=None):
    """명령을 실행하고 출력을 그대로 보여 준다. 실패하면 멈춘다."""
    print("$", cmd if isinstance(cmd, str) else " ".join(cmd))
    p = subprocess.Popen(cmd, cwd=cwd, shell=isinstance(cmd, str), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        print(line, end="")
    if p.wait() != 0:
        raise RuntimeError(f"명령이 실패했어요 (위 메시지를 확인하세요): {cmd}")

WORK = os.environ.get("LORA_WORK", "/content")
SD_SCRIPTS = os.path.join(WORK, "sd-scripts")
SD_SCRIPTS_TAG = "v0.11.1"  # kohya-ss/sd-scripts (Apache-2.0), 시험한 버전으로 고정

try:
    import torch
    if not torch.cuda.is_available() and not os.environ.get("LORA_ALLOW_CPU"):
        raise SystemExit("GPU 가 없어요. 메뉴 '런타임 → 런타임 유형 변경 → T4 GPU' 를 고르고 다시 '모두 실행' 하세요.")
except ImportError:
    pass

if not os.path.isdir(SD_SCRIPTS):
    run(["git", "clone", "--depth", "1", "--branch", SD_SCRIPTS_TAG, "https://github.com/kohya-ss/sd-scripts.git", SD_SCRIPTS])
if not os.environ.get("LORA_SKIP_INSTALL"):
    run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=SD_SCRIPTS)
    run([sys.executable, "-m", "pip", "install", "-q", "onnx", "onnxruntime"])
print("준비 끝")
''')

code(r'''
#@title 3. 그림 불러오기
import glob, shutil
from PIL import Image

if os.environ.get("LORA_DRIVE"):  # 시험용: 드라이브 대신 이 폴더
    DRIVE = os.environ["LORA_DRIVE"]
else:
    from google.colab import drive
    drive.mount("/content/drive")
    DRIVE = "/content/drive/MyDrive"

SRC = os.path.join(DRIVE, DRIVE_FOLDER, LORA_NAME)
OUT = os.path.join(DRIVE, DRIVE_FOLDER, "결과", LORA_NAME)
if not os.path.isdir(SRC):
    raise SystemExit(f"그림 폴더가 없어요: 내 드라이브/{DRIVE_FOLDER}/{LORA_NAME}\n드라이브에 폴더를 만들고 그림을 넣은 뒤 다시 실행하세요.")

EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
files = sorted(f for f in os.listdir(SRC) if f.lower().endswith(EXTS))
if len(files) < 5:
    raise SystemExit(f"그림이 {len(files)}장뿐이에요. 적어도 10장, 되도록 20장 이상 넣어 주세요.")

# 한 바퀴에 그림을 몇 번씩 볼지 (그림 수 x 반복 이 캐릭터 약 320, 그림체 약 300 이 되게)
REPEATS = max(1, round((320 if CHARACTER else 300) / len(files)))
TRAIN = os.path.join(WORK, "train")
IMG_DIR = os.path.join(TRAIN, f"{REPEATS}_{LORA_NAME}")  # sd-scripts 형식: 반복_이름
shutil.rmtree(TRAIN, ignore_errors=True)
os.makedirs(IMG_DIR)
own_caption = 0
for i, f in enumerate(files):
    im = Image.open(os.path.join(SRC, f))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):  # 투명한 곳은 흰색으로 (그냥 바꾸면 검게 돼요)
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    if min(im.size) < 256:
        print(f"  작은 그림이에요 (흐리게 배울 수 있어요): {f} {im.size}")
    stem = f"{i:03d}"
    im.save(os.path.join(IMG_DIR, stem + ".png"))
    txt = os.path.splitext(os.path.join(SRC, f))[0] + ".txt"
    if os.path.exists(txt):
        shutil.copy(txt, os.path.join(IMG_DIR, stem + ".txt"))
        own_caption += 1
print(f"그림 {len(files)}장 (설명 파일 있는 그림 {own_caption}장), 한 바퀴에 {REPEATS}번씩 봐요.")
''')

code(r'''
#@title 4. 그림 설명 붙이기
# WD14 태거(SmilingWolf/wd-v1-4-convnext-tagger-v2, Apache-2.0)로 그림마다 단어를 뽑고, 맨 앞에 LoRA 이름을 붙인다.
# 캐릭터면 머리·눈 색처럼 캐릭터에 늘 붙는 단어는 빼서 그 특징이 이름에 담기게 한다.
need = [p for p in glob.glob(os.path.join(IMG_DIR, "*.png")) if not os.path.exists(p[:-4] + ".txt")]
if need and AUTO_CAPTION:
    try:
        run([sys.executable, "finetune/tag_images_by_wd14_tagger.py", IMG_DIR, "--onnx", "--batch_size", "4",
             "--thresh", "0.35", "--caption_extension", ".tagger", "--remove_underscore",
             "--model_dir", os.path.join(WORK, "wd14_tagger_model")], cwd=SD_SCRIPTS)
    except Exception as e:
        print("자동 설명을 못 붙였어요. 이름만 붙여서 계속해요:", e)

TRAIT = re.compile(r"(hair|eyes|eyebrows|skin|ears|horns|tail|freckles|mole)\b")
for p in glob.glob(os.path.join(IMG_DIR, "*.png")):
    cap = p[:-4] + ".txt"
    if os.path.exists(cap):  # 직접 쓴 설명: 이름이 없으면 앞에 붙인다
        text = open(cap, encoding="utf-8").read().strip()
        tags = [t.strip() for t in text.split(",") if t.strip()]
    else:
        tg = p[:-4] + ".tagger"
        tags = [t.strip() for t in open(tg, encoding="utf-8").read().split(",") if t.strip()] if os.path.exists(tg) else []
        if CHARACTER:
            tags = [t for t in tags if not TRAIT.search(t)]
    tags = [LORA_NAME] + [t for t in tags if t != LORA_NAME]
    open(cap, "w", encoding="utf-8").write(", ".join(tags))
    if os.path.exists(p[:-4] + ".tagger"):
        os.remove(p[:-4] + ".tagger")
sample = sorted(glob.glob(os.path.join(IMG_DIR, "*.txt")))[:3]
for s in sample:
    print(os.path.basename(s), ":", open(s, encoding="utf-8").read()[:200])
''')

code(r'''
#@title 5. 학습 (캐릭터 약 20분, 그림체 약 30분)
import math
BATCH = 2
steps = math.ceil(len(files) * REPEATS / BATCH) * EPOCHS
DIM, ALPHA = (16, 8) if CHARACTER else (32, 16)
os.makedirs(OUT, exist_ok=True)
sample_prompt = (f"{LORA_NAME}, full body, standing, simple background, white background --n lowres, bad anatomy, blurry --w 512 --h 768 --d 42 --s 20"
                 if CHARACTER else f"{LORA_NAME}, a small castle on a hill, trees --n lowres, blurry --w 768 --h 512 --d 42 --s 20")
prompt_file = os.path.join(WORK, "sample_prompts.txt")
open(prompt_file, "w", encoding="utf-8").write(sample_prompt + "\n")
print(f"모두 {steps}걸음, {EPOCHS}바퀴. 2바퀴마다 중간 결과와 미리보기 그림을 드라이브에 저장해요.")

args = [
    "--pretrained_model_name_or_path", BASE_MODEL,
    "--train_data_dir", TRAIN, "--output_dir", OUT, "--output_name", LORA_NAME,
    "--save_model_as", "safetensors", "--save_precision", "fp16", "--save_every_n_epochs", "2",
    "--network_module", "networks.lora", "--network_dim", str(DIM), "--network_alpha", str(ALPHA),
    "--resolution", "512,512", "--enable_bucket", "--min_bucket_reso", "256", "--max_bucket_reso", "768", "--bucket_reso_steps", "64",
    "--train_batch_size", str(BATCH), "--max_train_epochs", str(EPOCHS),
    "--learning_rate", "1e-4", "--unet_lr", "1e-4", "--text_encoder_lr", "5e-5",
    "--lr_scheduler", "cosine", "--lr_warmup_steps", str(int(steps * 0.05)),
    "--optimizer_type", "AdamW", "--mixed_precision", os.environ.get("LORA_PRECISION", "fp16"),
    "--caption_extension", ".txt", "--shuffle_caption", "--keep_tokens", "1",
    "--cache_latents", "--seed", "42", "--max_data_loader_n_workers", "2",
    "--sample_every_n_epochs", "2", "--sample_prompts", prompt_file, "--sample_sampler", "euler_a",
]
if not os.environ.get("LORA_ALLOW_CPU"):
    args += ["--sdpa"]
args += os.environ.get("LORA_EXTRA_ARGS", "").split()
run([sys.executable, "-m", "accelerate.commands.launch", "--num_processes", "1", "--num_machines", "1",
     "--mixed_precision", os.environ.get("LORA_PRECISION", "fp16"), "--dynamo_backend", "no",
     "train_network.py", *args], cwd=SD_SCRIPTS)
FINAL = os.path.join(OUT, LORA_NAME + ".safetensors")
print("다 됐어요:", FINAL)
''')

code(r'''
#@title 6. 받기
# 드라이브의 '내 드라이브/LoRA학습/결과/이름/' 에도 저장돼 있어요. 미리보기 그림은 그 안의 sample 폴더에.
print(f"""그림 도구에서 쓰는 법
1. {LORA_NAME}.safetensors 를 C:\\AI-PIC\\ComfyUI_windows_portable\\ComfyUI\\models\\loras 에 넣어요.
2. 그림 도구의 'LoRA' 칸에서 '목록 새로 읽기' → {LORA_NAME} 고르기. '이름 단어' 를 켜 두면 '{LORA_NAME}' 이 프롬프트에 붙어요.
3. 세기는 0.8 에서 시작해서, 너무 똑같으면 내리고 덜 닮으면 올려요.
중간 결과({LORA_NAME}-000004.safetensors 처럼 숫자가 붙은 것)도 같은 방법으로 써 볼 수 있어요. 덜 배운 쪽이 더 유연할 때가 있어요.""")
if not os.environ.get("LORA_DRIVE"):
    from google.colab import files
    files.download(FINAL)
''')

nb = {"nbformat": 4, "nbformat_minor": 0,
      "metadata": {"colab": {"provenance": [], "gpuType": "T4"}, "accelerator": "GPU",
                   "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
      "cells": cells}
json.dump(nb, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok", len(cells), "cells")
