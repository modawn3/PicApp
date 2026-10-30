"""프리셋세트_v1 (API 변환본) -> PicApp/presets/*/ 생성"""
import json, os, shutil, sys
S = sys.argv[1]  # scratchpad
API = os.path.join(S, "api"); OUT = os.path.join(S, "PicApp", "presets")
shutil.rmtree(OUT, ignore_errors=True)

def wf(name): return json.load(open(os.path.join(API, name), encoding="utf-8"))
def text(n, wfj): return wfj[n]["inputs"]["text"]

NEG_HINT = "나오면 안 되는 것. 없애고 싶은 것도 여기에 써요."
def seed_field(*nodes):
    return {"id": "seed", "type": "seed", "label": "시드", "hint": "같은 캐릭터를 다시 얻으려면 '매번 새로'를 끄고 숫자를 그대로 두세요.",
            "targets": [{"node": n, "input": "seed"} for n in nodes]}

presets = {}

def palette_field():
    return {"id": "palette", "type": "palette", "label": "색 팔레트",
            "hint": "그릴 때는 색 이름을 프롬프트에 붙여 분위기를 맞추고, 그린 뒤에는 모든 색을 팔레트 색으로 바꿔요. 선 색(검정 계열)과 흰색도 꼭 넣으세요.",
            "targets": [{"node": "3", "input": "text", "append": True}]}

def add_quality(w, pos, neg, plain_pos="3"):
    """2단계 그리기(1.5배 다시 다듬기) + 얼굴·손 자동 다듬기 노드를 붙인다.
    pos/neg: 1단계 KSampler 가 쓰는 conditioning (자세 참고는 ControlNet 출력)."""
    ck = "2"
    w["20"] = {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["6", 0], "upscale_method": "nearest-exact", "scale_by": 1.5},
               "_meta": {"title": "2단계: 1.5배 키우기"}}
    w["21"] = {"class_type": "KSampler", "inputs": {"model": [ck, 0], "positive": pos, "negative": neg, "latent_image": ["20", 0],
               "seed": 0, "steps": 20, "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 0.45},
               "_meta": {"title": "2단계: 세부 다시 그리기 (denoise 0.45)"}}
    w["7"] = {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["21", 0], "vae": [ck, 2], "tile_size": 512, "overlap": 64,
              "temporal_size": 64, "temporal_overlap": 8}, "_meta": {"title": "VAE Decode (타일, 메모리 절약)"}}
    def detailer(image, positive, detector, denoise, title, crop=3.0):
        return {"class_type": "FaceDetailer", "_meta": {"title": title}, "inputs": {
            "image": image, "model": [ck, 0], "clip": [ck, 1], "vae": [ck, 2], "positive": positive, "negative": ["4", 0],
            "bbox_detector": detector, "guide_size": 512, "guide_size_for": True, "max_size": 768, "seed": 0, "steps": 20,
            "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": denoise, "feather": 5, "noise_mask": True,
            "force_inpaint": True, "bbox_threshold": 0.5, "bbox_dilation": 10, "bbox_crop_factor": crop,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93, "sam_bbox_expansion": 0,
            "sam_mask_hint_threshold": 0.7, "sam_mask_hint_use_negative": "False", "drop_size": 10, "wildcard": "",
            "cycle": 1, "inpaint_model": False, "noise_mask_feather": 20, "tiled_encode": False, "tiled_decode": False}}
    w["22"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": "bbox/face_yolov8m.pt"}, "_meta": {"title": "얼굴 찾기"}}
    w["23"] = detailer(["7", 0], [plain_pos, 0], ["22", 0], 0.4, "얼굴 자동 다듬기")
    w["24"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": "bbox/hand_yolov8s.pt"}, "_meta": {"title": "손 찾기"}}
    w["25"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "detailed hands, five fingers", "clip": [ck, 1]},
               "_meta": {"title": "손 다듬기 프롬프트"}}
    # 손은 좁게 잘라서 다시 그린다. 넓게 자르면 손 주변에 방패·기계 같은 물건을 새로 그려 넣는다.
    w["26"] = detailer(["23", 0], ["25", 0], ["24", 0], 0.45, "손 자동 다듬기", crop=2.0)
    for n in ("8", "11"):  # 원본 저장, 배경 제거는 다듬은 그림을 받는다
        w[n]["inputs"]["image" if n == "11" else "images"] = ["26", 0]

QUALITY_SEEDS = ["21", "23", "26"]

def add_ref(w):
    """캐릭터 참고 그림 (IP-Adapter PLUS): 그림을 올리면 얼굴·옷·색을 따라 그린다. 안 올리면 건너뛴다."""
    w["52"] = {"class_type": "LoadImage", "inputs": {"image": "character_reference.png"}, "_meta": {"title": "캐릭터 참고 그림"}}
    w["51"] = {"class_type": "PrepImageForClipVision", "inputs": {"image": ["52", 0], "interpolation": "LANCZOS",
               "crop_position": "pad", "sharpening": 0.0}, "_meta": {"title": "정사각으로 (자르지 않고 여백)"}}
    w["50"] = {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["2", 0], "preset": "PLUS (high strength)"},
               "_meta": {"title": "IP-Adapter PLUS 불러오기"}}
    w["53"] = {"class_type": "IPAdapterAdvanced", "inputs": {"model": ["50", 0], "ipadapter": ["50", 1], "image": ["51", 0],
               "weight": 0.7, "weight_type": "linear", "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
               "embeds_scaling": "V only"}, "_meta": {"title": "캐릭터 닮게"}}
    for n, node in w.items():  # 그리는 노드(1·2단계, 얼굴·손 다듬기)가 모두 캐릭터를 따라가게
        if n != "50" and node["inputs"].get("model") == ["2", 0]:
            node["inputs"]["model"] = ["53", 0]

def ref_fields():
    return [
        {"id": "ref", "type": "image", "label": "캐릭터 참고 그림 (이 캐릭터처럼)", "required": False, "flatten": True,
         "targets": [{"node": "52", "input": "image"}], "requires": ["IPAdapterUnifiedLoader", "IPAdapterAdvanced"],
         "setup": "캐릭터 닮게 그리기 준비", "bypass_empty": [{"node": "53", "input": "model"}],
         "hint": "이미 그린 캐릭터 그림을 올리면 얼굴·옷·색을 보고 새 자세로 그려요. 결과 카드의 '다른 기능으로 보내기'로도 넣을 수 있어요. 비워 두면 설명만 보고 그려요."},
        {"id": "ref_weight", "type": "number", "label": "캐릭터 닮게 하는 세기", "default": 0.7, "min": 0.2, "max": 1.2, "step": 0.05,
         "targets": [{"node": "53", "input": "weight"}],
         "hint": "덜 닮으면 올리고, 참고 그림의 자세나 배경까지 따라오면 내려요. 0.6~0.8 이 무난해요."}]
# 캐릭터만 그리기: steampunk·mechanical 같은 말이 들어가면 DreamShaper 는 큰 기계·바퀴·톱니를 옆에 그려 넣는다.
SOLO_POS = "(solo:1.2), standing alone, (plain white background:1.2), empty background"
SOLO_NEG = ("(machine, machinery, engine, vehicle, motorcycle, wheel, tire:1.3), (giant gears, large cogwheel, clockwork machine:1.2), "
            "(shield, weapon, holding large object:1.2), robot, mecha, pipes, scenery, background objects, furniture, "
            "multiple views, character sheet, reference sheet, multiple girls, (extra legs, extra arms, third leg:1.3)")
def solo_field():
    return {"id": "solo", "type": "toggle", "label": "캐릭터만 그리기 (주변 기계·바퀴·방패 같은 물건 빼기)", "default": True,
            "hint": "켜 두면 '피할 것'에 직접 쓰지 않아도 큰 기계·탈것·방패·배경 물건·여분의 팔다리를 피하게 해요. 일부러 탈것이나 큰 무기를 그릴 때만 끄세요.",
            "add_text": [{"node": "3", "input": "text", "text": SOLO_POS}, {"node": "4", "input": "text", "text": SOLO_NEG}]}

FACE_NEEDS = ["FaceDetailer", "UltralyticsDetectorProvider"]
def quality_fields():
    return [
        {"id": "hires", "type": "toggle", "label": "2단계로 그리기 (1.5배로 키워 다시 다듬기)", "default": True, "group_label": "품질",
         "hint": "선과 장식이 또렷해져요. 결과가 1.5배 커지고 시간이 더 걸려요.",
         "bypass_off": [{"node": "21", "input": "latent_image"}, {"node": "20", "input": "samples"}]},
        {"id": "face", "type": "toggle", "label": "얼굴 자동 다듬기", "default": True, "requires": FACE_NEEDS,
         "bypass_off": [{"node": "23", "input": "image"}]},
        {"id": "hands", "type": "toggle", "label": "손 자동 다듬기", "default": True, "requires": FACE_NEEDS,
         "hint": "얼굴과 손을 찾아 확대해서 다시 그려요. 못 찾으면 그대로 둬요.",
         "bypass_off": [{"node": "26", "input": "image"}],
         "targets": []}]

def palette_step(nodes):
    return [{"step": "palette", "from_node": nodes, "label": "팔레트 맞춤", "params_from": "palette", "enabled_key": "snap"}]

w = wf("01_캐릭터_그리기.json"); p = text("3", w)
subj, style = p.split(", full body", 1)
add_quality(w, ["3", 0], ["4", 0])
presets["01_character"] = (w, {
  "name": "캐릭터 그리기", "group": "그리기", "order": 1,
  "description": "설명을 쓰면 캐릭터 일러스트를 그리고 배경을 지워 줘요. 품질 칸을 모두 끄면 약 10초, 켜면 더 걸려요.",
  "fields": [
    {"id": "subject", "type": "textarea", "label": "그릴 것 (주제)", "default": subj,
     "hint": "한글이나 영어로 결과 모습을 써요. 한글은 영어로 바꿔서 넣어요. 그림체 단어는 아래 고급 설정에 따로 있어요."},
    {"id": "style", "type": "textarea", "label": "그림체 단어", "advanced": True, "default": "full body" + style,
     "targets": [{"node": "3", "input": "text", "template": "{subject}, {style}"},
                 {"node": "25", "input": "text", "template": "{subject}, detailed hands, five fingers, {style}"}]},
    {"id": "negative", "type": "textarea", "label": "피할 것 (부정 프롬프트)", "advanced": True, "default": text("4", w),
     "hint": NEG_HINT, "targets": [{"node": "4", "input": "text"}]},
    solo_field(), palette_field(),
    {"id": "size", "type": "choice", "label": "크기", "default": "square",
     "hint": "전신이 잘리면 '세로 전신'으로 바꾸세요.", "options": [
      {"value": "square", "label": "정사각 512 (2단계면 768) · 에셋 256x256", "set": [
        {"node": "5", "input": "width", "value": 512}, {"node": "5", "input": "height", "value": 512},
        {"node": "9", "input": "width", "value": 256}, {"node": "9", "input": "height", "value": 256}]},
      {"value": "tall", "label": "세로 전신 512x768 (2단계면 768x1152) · 에셋 256x384", "set": [
        {"node": "5", "input": "width", "value": 512}, {"node": "5", "input": "height", "value": 768},
        {"node": "9", "input": "width", "value": 256}, {"node": "9", "input": "height", "value": 384}]}]},
    *quality_fields(), seed_field("6", *QUALITY_SEEDS)],
  "outputs": [{"node": "8", "label": "원본"}, {"node": "12", "label": "투명", "send": False},
              {"node": "10", "label": "게임 에셋 (투명, 작게)", "send": False}],
  "postprocess": palette_step(["8", "12", "10"])})

w = wf("02_컨셉아트.json")
presets["02_concept"] = (w, {
  "name": "컨셉아트", "group": "그리기", "order": 2,
  "description": "가로로 긴 배경·장면 그림. 768 초안을 1.5배로 다시 그려 1152로 완성해요. 약 30초.",
  "fields": [
    {"id": "prompt", "type": "textarea", "label": "그릴 장면", "rows": 5, "default": text("3", w),
     "hint": "꼭 나와야 할 대상은 (단어:1.15)처럼 강조 (1.1~1.3). 대상이 겹치면 on the left side / on the right side / in the background 로 위치를 나눠요.",
     "targets": [{"node": "3", "input": "text"}]},
    {"id": "negative", "type": "textarea", "label": "피할 것 (부정 프롬프트)", "advanced": True, "default": text("4", w),
     "hint": NEG_HINT, "targets": [{"node": "4", "input": "text"}]},
    palette_field(), seed_field("6", "10")],
  "outputs": [{"node": "8", "label": "초안 768"}, {"node": "12", "label": "완성 1152"}],
  "postprocess": palette_step(["12"])})

w = wf("03_자세참고_캐릭터.json"); p = text("3", w)
subj, style = p.split(", full body", 1)
add_quality(w, ["17", 0], ["17", 1])
add_ref(w)
def size(v, label, W, H, w2, h2):
    return {"value": v, "label": label, "ratio": W / H, "set": [
        {"node": "5", "input": "width", "value": W}, {"node": "5", "input": "height", "value": H},
        {"node": "9", "input": "width", "value": w2}, {"node": "9", "input": "height", "value": h2}]}
presets["03_pose"] = (w, {
  "name": "자세 참고 캐릭터", "group": "그리기", "order": 3,
  "description": "참고 그림의 자세를 따라 캐릭터를 그리고 배경을 지워 줘요. 품질 칸을 모두 끄면 약 15초, 켜면 더 걸려요.",
  "fields": [
    {"id": "pose", "type": "image", "label": "자세 참고 그림", "targets": [{"node": "13", "input": "image"}],
     "hint": "사진이나 그림 아무거나. 전신이 보이고 머리 위·발 아래에 여백이 있으면 좋아요. '3D 자세 만들기'에서 보낼 수도 있어요."},
    {"id": "skeleton", "type": "toggle", "label": "올린 그림이 이미 뼈대 그림이에요 (OpenPose 막대 그림)", "default": False,
     "skeleton_for": "pose", "hint": "뼈대 그림을 올리면 저절로 켜져요. 뼈대를 다시 뽑지 않고 그대로 써요.",
     "bypass_on": [{"node": "14", "input": "image"}]},
    *ref_fields(),
    {"id": "subject", "type": "textarea", "label": "그릴 것 (주제)", "default": subj,
     "hint": "같은 캐릭터로 자세만 바꾸려면 위 캐릭터 참고 그림을 넣고, 설명도 처음 그릴 때와 같게 써요."},
    {"id": "style", "type": "textarea", "label": "그림체 단어", "advanced": True, "default": "full body" + style,
     "targets": [{"node": "3", "input": "text", "template": "{subject}, {style}"},
                 {"node": "25", "input": "text", "template": "{subject}, detailed hands, five fingers, {style}"}]},
    {"id": "negative", "type": "textarea", "label": "피할 것 (부정 프롬프트)", "advanced": True, "default": text("4", w),
     "hint": NEG_HINT, "targets": [{"node": "4", "input": "text"}]},
    solo_field(), palette_field(),
    {"id": "size", "type": "choice", "label": "비율", "default": "tall", "auto_from": "pose",
     "hint": "참고 그림을 올리면 가장 가까운 비율로 저절로 바뀌어요. 비율이 다르면 머리·발이 잘려요.",
     "options": [size("tall", "세로 512x768", 512, 768, 256, 384), size("square", "정사각 512x512", 512, 512, 256, 256),
                 size("34", "3:4 512x704", 512, 704, 256, 352)]},
    {"id": "strength", "type": "number", "label": "자세 따라가기 세기", "advanced": True, "default": 1.0,
     "min": 0.3, "max": 1.5, "step": 0.05, "targets": [{"node": "17", "input": "strength"}],
     "hint": "자세가 틀리면 올리기."},
    {"id": "end", "type": "number", "label": "자세 적용 끝나는 지점", "advanced": True, "default": 0.8,
     "min": 0.3, "max": 1.0, "step": 0.05, "targets": [{"node": "17", "input": "end_percent"}],
     "hint": "그림이 딱딱하거나 치비(큰 머리·짧은 다리)가 잘 안 나오면 0.6~0.7로. 세기와 같이 내리지는 마세요."},
    *quality_fields(), seed_field("6", *QUALITY_SEEDS)],
  "outputs": [{"node": "15", "label": "뼈대 확인", "send": False}, {"node": "8", "label": "원본"},
              {"node": "12", "label": "투명", "send": False}, {"node": "10", "label": "게임 에셋 (투명, 작게)", "send": False}],
  "postprocess": palette_step(["8", "12", "10"])})

fixes = [
  ("04_fix_face", "04_확대수정_얼굴.json", "얼굴 고치기", 4, "눈·표정을 확대해서 다듬어요.",
   "얼굴(눈·코·입)을 칠하세요. 머리카락과 안경은 칠하지 않으면 그대로예요.",
   "얼굴형만 다듬기 0.45, 표정 바꾸기 0.75."),
  ("05_fix_hand", "05_확대수정_손.json", "손 고치기", 5, "손가락을 확대해서 고쳐요.",
   "손을 하나씩 칠하세요. 두 손을 한 번에 칠하지 말고 한 손씩 따로 돌려요.",
   "손가락이 계속 이상하면 '매번 새로'를 켜고 5~10번 돌려서 골라요. 맨손이면 그릴 모습에서 gloves 를 지우세요."),
  ("06_fix_item", "06_확대수정_소품교체.json", "소품 바꾸기", 6, "모자 같은 소품을 바꾸거나 없애요.",
   "바꿀 소품 전체와 없앨 것을 칠하세요. 칠한 크기가 새 소품 크기가 돼요.",
   "새 소품의 색·재질은 옷과 맞춰 쓰고, 없앨 것은 '없앨 것' 맨 앞에 써요."),
  ("07_fix_blend", "07_확대수정_어울림보정.json", "어울림 보정", 7, "고친 부분의 색·선을 주변과 맞춰요. 마무리용.",
   "다른 고치기로 만든 결과를 올리고, 고친 부분과 그 주변을 넓게 칠하세요.",
   "너무 안 바뀌면 0.45, 모양까지 바뀌면 0.25."),
]
for pid, fn, name, order, desc, paint_hint, den_hint in fixes:
    w = wf(fn)
    presets[pid] = (w, {
      "name": name, "group": "고치기", "order": order, "description": desc,
      "fields": [
        {"id": "image", "type": "mask_image", "label": "고칠 그림", "targets": [{"node": "3", "input": "image"}],
         "hint": paint_hint},
        {"id": "positive", "type": "textarea", "label": "고친 뒤 모습", "default": text("6", w),
         "hint": "명령문이 아니라 결과 모습으로 써요. 예: '모자 없애기' 대신 '맨머리', 없앨 것은 아래 칸에.",
         "targets": [{"node": "6", "input": "text"}]},
        {"id": "negative", "type": "textarea", "label": "없앨 것", "default": text("7", w),
         "hint": NEG_HINT, "targets": [{"node": "7", "input": "text"}]},
        {"id": "denoise", "type": "number", "label": "바꾸는 정도", "default": w["9"]["inputs"]["denoise"],
         "min": 0.1, "max": 1.0, "step": 0.05, "hint": den_hint, "targets": [{"node": "9", "input": "denoise"}]},
        seed_field("9")],
      "outputs": [{"node": "12", "label": "수정본"}, {"node": "14", "label": "투명", "send": False},
                  {"node": "5", "label": "잘린 부분 확인", "send": False}]})

# ---------- 08 분위기 바꾸기 (img2img + 선 붙잡는 ControlNet lineart) ----------
NEG = text("4", wf("01_캐릭터_그리기.json"))
w = {
 "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "dreamshaper_8.safetensors"}},
 "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 1]}, "_meta": {"title": "긍정 (설명 + 분위기 + 그림체)"}},
 "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 1]}, "_meta": {"title": "부정"}},
 "13": {"class_type": "LoadImage", "inputs": {"image": "mood_source.png"}, "_meta": {"title": "바꿀 그림"}},
 "30": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["13", 0], "upscale_method": "lanczos", "megapixels": 0.3,
        "resolution_steps": 8}, "_meta": {"title": "SD 1.5 크기로 맞추기 (약 0.3MP)"}},
 "31": {"class_type": "VAEEncode", "inputs": {"pixels": ["30", 0], "vae": ["2", 2]}},
 "32": {"class_type": "LineArtPreprocessor", "inputs": {"image": ["30", 0], "coarse": "disable", "resolution": 512}, "_meta": {"title": "선 뽑기"}},
 "15": {"class_type": "PreviewImage", "inputs": {"images": ["32", 0]}, "_meta": {"title": "선 확인"}},
 "33": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "control_v11p_sd15_lineart_fp16.safetensors"}},
 "34": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "control_net": ["33", 0],
        "image": ["32", 0], "strength": 0.8, "start_percent": 0.0, "end_percent": 0.9}, "_meta": {"title": "모양 지키기"}},
 "6": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["34", 0], "negative": ["34", 1], "latent_image": ["31", 0],
       "seed": 0, "steps": 30, "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 0.55}, "_meta": {"title": "다시 그리기"}},
 "20": {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["6", 0], "upscale_method": "nearest-exact", "scale_by": 1.5}},
 "21": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["34", 0], "negative": ["34", 1], "latent_image": ["20", 0],
        "seed": 0, "steps": 20, "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 0.45}},
 "7": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["21", 0], "vae": ["2", 2], "tile_size": 512, "overlap": 64,
       "temporal_size": 64, "temporal_overlap": 8}},
 "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "08_mood"}},
 "11": {"class_type": "InspyrenetRembg", "inputs": {"image": ["7", 0], "torchscript_jit": "default"}},
 "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "08_mood_transparent"}},
}
MOODS = [("밤", "night, moonlight, dark blue tones, starry sky, soft glow"),
         ("노을", "sunset, golden hour, warm orange light, long shadows"),
         ("비 오는 날", "rainy day, rain, wet surfaces, overcast, gloomy, reflections"),
         ("눈", "snowy, winter, falling snow, cold blue tones, frost"),
         ("어두운 판타지", "dark fantasy, ominous, dramatic shadows, desaturated, mist"),
         ("밝고 화사하게", "bright, cheerful, vibrant colors, soft daylight"),
         ("스팀펑크로", "steampunk, brass and copper, gears, steam, victorian industrial"),
         ("중세 마법사로", "medieval fantasy, wizard, magical glow, runes, robes, castle")]
presets["08_mood"] = (w, {
  "name": "분위기 바꾸기", "group": "바꾸기", "order": 8,
  "description": "이미 그린 그림의 분위기(시간, 날씨, 진영 느낌)를 바꿔요. 선을 붙잡아 두어서 모양과 자세는 남아요.",
  "fields": [
    {"id": "image", "type": "image", "label": "바꿀 그림", "flatten": True, "targets": [{"node": "13", "input": "image"}],
     "hint": "결과 카드의 '다른 기능으로 보내기'로도 넣을 수 있어요. 투명한 곳은 흰색으로 채워요."},
    {"id": "content", "type": "textarea", "label": "그림 설명", "rows": 2, "default": "a girl, full body",
     "hint": "그림에 무엇이 있는지 짧게 써요. 한글도 돼요. 예: 기사 소녀, 전신"},
    {"id": "mood", "type": "textarea", "label": "바꿀 분위기", "rows": 2, "default": MOODS[0][1],
     "presets": [{"label": k, "value": v} for k, v in MOODS],
     "hint": "버튼을 누르면 채워져요. 직접 써도 돼요."},
    {"id": "style", "type": "textarea", "label": "그림체 단어", "advanced": True,
     "default": "anime style, clean lineart, flat colors, cel shading, highly detailed",
     "targets": [{"node": "3", "input": "text", "template": "{content}, {mood}, {style}"}]},
    {"id": "negative", "type": "textarea", "label": "피할 것 (부정 프롬프트)", "advanced": True, "default": NEG,
     "hint": NEG_HINT, "targets": [{"node": "4", "input": "text"}]},
    {"id": "amount", "type": "number", "label": "얼마나 바꿀지 (조금 ~ 많이)", "default": 0.55, "min": 0.2, "max": 0.9, "step": 0.05,
     "targets": [{"node": "6", "input": "denoise"}],
     "hint": "0.3 쯤이면 색과 빛만, 0.55 는 옷 색과 배경 분위기까지, 0.8 이상이면 많이 바뀌어요."},
    {"id": "keep", "type": "toggle", "label": "모양 지키기 (선 붙잡기)", "default": True,
     "requires": ["LineArtPreprocessor"], "setup": "모양 지키기 준비",
     "hint": "많이 바꿔도 캐릭터 모양과 자세가 남아요. 끄면 더 자유롭게 바뀌어요.",
     "bypass_off": [{"node": "34", "input": {"0": "positive", "1": "negative"}}, {"node": "15", "input": "images"}]},
    {"id": "keep_strength", "type": "number", "label": "모양 지키는 세기", "advanced": True, "default": 0.8,
     "min": 0.2, "max": 1.5, "step": 0.05, "targets": [{"node": "34", "input": "strength"}],
     "hint": "모양이 너무 바뀌면 올리고, 분위기가 잘 안 바뀌면 내려요."},
    {"id": "hires", "type": "toggle", "label": "2단계로 그리기 (1.5배로 키워 다시 다듬기)", "default": False,
     "hint": "결과가 1.5배 커지고 또렷해져요. 시간이 더 걸려요.",
     "bypass_off": [{"node": "21", "input": "latent_image"}, {"node": "20", "input": "samples"}]},
    {"id": "rembg", "type": "toggle", "label": "배경 제거한 그림도 만들기", "default": False,
     "bypass_off": [{"node": "12", "input": "images"}]},
    palette_field(), seed_field("6", "21")],
  "outputs": [{"node": "8", "label": "결과"}, {"node": "12", "label": "투명", "send": False},
              {"node": "15", "label": "선 확인", "send": False}],
  "postprocess": palette_step(["8", "12"])})

# ---------- 09 도트 만들기 (ComfyUI 는 배경 제거만, 도트 변환은 postprocess/pixel.py) ----------
w = {
 "13": {"class_type": "LoadImage", "inputs": {"image": "pixel_source.png"}, "_meta": {"title": "도트로 만들 그림"}},
 "40": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["13", 0], "alpha": ["13", 1]}, "_meta": {"title": "투명 그대로"}},
 "11": {"class_type": "InspyrenetRembg", "inputs": {"image": ["13", 0], "torchscript_jit": "default"}, "_meta": {"title": "배경 제거"}},
 "8": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "09_pixel_source"}},
}
presets["09_pixel"] = (w, {
  "name": "도트 만들기", "group": "바꾸기", "order": 9, "run_label": "만들기",
  "description": "그림을 게임용 도트(픽셀아트)로 바꿔요. 줄이고, 색을 줄이고, 배경을 투명하게 해요.",
  "fields": [
    {"id": "image", "type": "image", "label": "도트로 만들 그림", "targets": [{"node": "13", "input": "image"}],
     "hint": "결과 카드의 '다른 기능으로 보내기'로도 넣을 수 있어요. 투명 그림을 보내면 그대로 써요."},
    {"id": "bg", "type": "choice", "label": "배경", "default": "remove", "auto_alpha_from": "image",
     "hint": "투명한 그림을 올리면 저절로 '투명 그대로'로 바뀌어요.", "options": [
      {"value": "remove", "label": "배경 지우기", "alpha": False, "set": [{"node": "8", "input": "images", "value": ["11", 0]}]},
      {"value": "keep", "label": "투명 그대로 (이미 배경이 없는 그림)", "alpha": True, "set": [{"node": "8", "input": "images", "value": ["40", 0]}]}]},
    {"id": "size", "type": "choice", "label": "도트 크기 (가장 긴 쪽)", "default": "64",
     "options": [{"value": str(n), "label": f"{n} 픽셀"} for n in (16, 24, 32, 48, 64, 96, 128)],
     "hint": "작을수록 옛날 게임 느낌이에요. 32~64가 캐릭터에 무난해요."},
    {"id": "square", "type": "toggle", "label": "정사각 칸에 맞추기 (아래 가운데 정렬)", "default": True,
     "hint": "모든 결과가 같은 칸 크기가 되어 스프라이트 시트로 묶기 좋아요."},
    {"id": "colors", "type": "number", "label": "색 수 (팔레트를 안 쓸 때)", "default": 16, "min": 4, "max": 64, "step": 1},
    {"id": "palette", "type": "palette", "label": "색 팔레트", "simple": True,
     "hint": "고르면 도트가 이 팔레트 색만 써요. 안 고르면 그림에서 위 색 수만큼 골라요."},
    {"id": "outline", "type": "toggle", "label": "1픽셀 외곽선 넣기", "default": False,
     "hint": "가장 어두운 색으로 둘레에 선을 둘러요. 배경 위에서 캐릭터가 잘 보여요."}],
  "outputs": [{"node": "8", "label": "배경 지운 원본", "hidden": True}],
  "postprocess": [{"step": "pixel", "from_node": ["8"], "label": "도트", "fields": ["size", "square", "colors", "palette", "outline"]}]})

# ---------- 10 스프라이트 애니메이션 (자세 그림마다 같은 시드로 한 장씩 → postprocess/sprite.py 가 시트·GIF) ----------
w = wf("03_자세참고_캐릭터.json"); p = text("3", w)
subj, style = p.split(", full body", 1)
add_quality(w, ["17", 0], ["17", 1])
for n in ("8", "9", "10"):  # 프레임은 투명 그림만 쓴다
    del w[n]
add_ref(w)
w["40"] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["13", 0], "alpha": ["13", 1]}, "_meta": {"title": "투명 그대로"}}
w["12"]["inputs"]["filename_prefix"] = "10_sprite_frame"
def frame_size(v, label, W, H):
    o = size(v, label, W, H, 0, 0)
    o["set"] = [t for t in o["set"] if t["node"] == "5"]
    return o
def off(fields):
    for f in fields:
        f["default"] = False
    return fields
presets["10_sprite"] = (w, {
  "name": "스프라이트 애니메이션", "group": "움직이기", "order": 11, "run_label": "만들기", "repeat_over": "poses",
  "description": "자세 그림을 순서대로 올리면 같은 캐릭터를 자세마다 그려서 스프라이트 시트와 움직임 미리보기(GIF)를 만들어요. 이미 그린 그림을 묶기만 할 수도 있어요.",
  "fields": [
    {"id": "how", "type": "choice", "label": "만드는 방법", "default": "draw", "options": [
      {"value": "draw", "label": "자세 그림대로 새로 그리기"},
      {"value": "bundle_rembg", "label": "이미 그린 그림 묶기 (배경 지우기)",
       "set": [{"node": "11", "input": "image", "value": ["13", 0]}], "remove": ["15"]},
      {"value": "bundle", "label": "이미 그린 그림 묶기 (투명 그대로)",
       "set": [{"node": "12", "input": "images", "value": ["40", 0]}], "remove": ["15"]}],
     "hint": "묶기만 하면 아래 '그릴 것'과 자세 칸은 쓰지 않아요."},
    {"id": "poses", "type": "images", "label": "프레임 그림 (순서대로)", "targets": [{"node": "13", "input": "image"}],
     "hint": "새로 그리기: 자세 참고 그림(사진도 돼요)을 동작 순서대로 올려요. 걷기는 4~8장이 무난해요. 묶기: 프레임 그림을 순서대로."},
    {"id": "skeleton", "type": "toggle", "label": "올린 그림이 이미 뼈대 그림이에요 (OpenPose 막대 그림)", "default": False,
     "skeleton_for": "poses", "hint": "'3D 자세 만들기'에서 보낸 뼈대 그림이면 저절로 켜져요. 뼈대를 다시 뽑지 않아 더 정확해요.",
     "bypass_on": [{"node": "14", "input": "image"}]},
    *ref_fields(),
    {"id": "subject", "type": "textarea", "label": "그릴 것 (주제)", "default": subj,
     "hint": "모든 프레임에 같은 설명과 같은 시드를 써요. 옷·색을 자세히 쓸수록 프레임끼리 덜 달라져요."},
    {"id": "style", "type": "textarea", "label": "그림체 단어", "advanced": True, "default": "full body" + style,
     "targets": [{"node": "3", "input": "text", "template": "{subject}, {style}"},
                 {"node": "25", "input": "text", "template": "{subject}, detailed hands, five fingers, {style}"}]},
    {"id": "negative", "type": "textarea", "label": "피할 것 (부정 프롬프트)", "advanced": True, "default": text("4", w),
     "hint": NEG_HINT, "targets": [{"node": "4", "input": "text"}]},
    solo_field(),
    {"id": "ratio", "type": "choice", "label": "비율", "default": "tall", "auto_from": "poses",
     "hint": "첫 프레임 그림을 올리면 가장 가까운 비율로 저절로 바뀌어요.",
     "options": [frame_size("tall", "세로 512x768", 512, 768), frame_size("square", "정사각 512x512", 512, 512),
                 frame_size("34", "3:4 512x704", 512, 704)]},
    {"id": "strength", "type": "number", "label": "자세 따라가기 세기", "advanced": True, "default": 1.0,
     "min": 0.3, "max": 1.5, "step": 0.05, "targets": [{"node": "17", "input": "strength"}]},
    {"id": "end", "type": "number", "label": "자세 적용 끝나는 지점", "advanced": True, "default": 0.8,
     "min": 0.3, "max": 1.0, "step": 0.05, "targets": [{"node": "17", "input": "end_percent"}]},
    *off(quality_fields()),
    seed_field("6", *QUALITY_SEEDS),
    {"id": "pixel", "type": "toggle", "label": "도트로 바꾸기", "default": True, "group_label": "시트",
     "hint": "모든 프레임을 같은 크기·같은 색으로 도트로 바꿔요."},
    {"id": "size", "type": "choice", "label": "도트 크기 (칸 한 변)", "default": "64",
     "options": [{"value": str(n), "label": f"{n} 픽셀"} for n in (16, 24, 32, 48, 64, 96, 128)]},
    {"id": "colors", "type": "number", "label": "색 수 (팔레트를 안 쓸 때)", "default": 16, "min": 4, "max": 64, "step": 1, "advanced": True},
    {"id": "palette", "type": "palette", "label": "색 팔레트 (도트)", "simple": True, "advanced": True,
     "hint": "고르면 도트가 이 팔레트 색만 써요."},
    {"id": "outline", "type": "toggle", "label": "1픽셀 외곽선 넣기 (도트)", "default": False, "advanced": True},
    {"id": "cell", "type": "choice", "label": "칸 크기 (도트로 안 바꿀 때)", "default": "256", "advanced": True,
     "options": [{"value": "128", "label": "128 픽셀"}, {"value": "256", "label": "256 픽셀"}, {"value": "0", "label": "줄이지 않기"}]},
    {"id": "columns", "type": "number", "label": "한 줄에 몇 칸 (0 = 모두 한 줄)", "default": 0, "min": 0, "max": 12, "step": 1,
     "hint": "Unity 에서는 Sprite Mode 를 Multiple 로 하고 Slice 의 Grid By Cell Size 에 칸 크기를 넣으면 잘라져요."},
    {"id": "frame_ms", "type": "number", "label": "미리보기 한 프레임 시간 (ms)", "default": 120, "min": 40, "max": 500, "step": 10,
     "hint": "작을수록 빨라요. 걷기는 100~150 이 무난해요."}],
  "outputs": [{"node": "15", "label": "뼈대 확인"}, {"node": "12", "label": "프레임"}],
  "postprocess": [{"step": "sprite", "from_node": ["12"], "label": "스프라이트",
                   "fields": ["pixel", "size", "colors", "palette", "outline", "cell", "columns", "frame_ms"]}]})

# ---------- 11 SDXL 고품질 다듬기 (마음에 든 그림을 SDXL img2img 로 한 번 더) ----------
TURBO, BASE = "DreamShaperXL_Turbo_v2_1.safetensors", "sd_xl_base_1.0.safetensors"
w = {
 "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": TURBO}, "_meta": {"title": "SDXL 모델"}},
 "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 1]}, "_meta": {"title": "긍정 (설명 + 그림체)"}},
 "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 1]}, "_meta": {"title": "부정"}},
 "13": {"class_type": "LoadImage", "inputs": {"image": "sdxl_source.png"}, "_meta": {"title": "다듬을 그림"}},
 "30": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["13", 0], "upscale_method": "lanczos", "megapixels": 1.0,
        "resolution_steps": 8}, "_meta": {"title": "SDXL 크기로 키우기 (약 1MP)"}},
 "31": {"class_type": "VAEEncodeTiled", "inputs": {"pixels": ["30", 0], "vae": ["2", 2], "tile_size": 512, "overlap": 64,
        "temporal_size": 64, "temporal_overlap": 8}, "_meta": {"title": "VAE Encode (타일, 메모리 절약)"}},
 "6": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["31", 0],
       "seed": 0, "steps": 8, "cfg": 2.0, "sampler_name": "dpmpp_sde", "scheduler": "karras", "denoise": 0.35},
       "_meta": {"title": "SDXL 로 다시 다듬기"}},
 "7": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["6", 0], "vae": ["2", 2], "tile_size": 512, "overlap": 64,
       "temporal_size": 64, "temporal_overlap": 8}, "_meta": {"title": "VAE Decode (타일, 메모리 절약)"}},
 "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "11_sdxl"}},
 "11": {"class_type": "InspyrenetRembg", "inputs": {"image": ["7", 0], "torchscript_jit": "default"}},
 "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "11_sdxl_transparent"}},
}
def ks(**kv): return [{"node": "6", "input": k, "value": v} for k, v in kv.items()]
presets["11_sdxl"] = (w, {
  "name": "고품질 다듬기 (SDXL)", "group": "바꾸기", "order": 10, "run_label": "다듬기",
  "description": "마음에 든 그림을 더 큰 SDXL 모델로 한 번 더 다듬어요. 1024 크기로 키우면서 선과 질감이 좋아져요. 느려요 (한 장에 1분 이상 걸릴 수 있어요).",
  "fields": [
    {"id": "image", "type": "image", "label": "다듬을 그림", "flatten": True, "targets": [{"node": "13", "input": "image"}],
     "hint": "결과 카드의 '다른 기능으로 보내기 → 고품질 다듬기'로 넣으면 편해요. 투명한 곳은 흰색으로 채워요."},
    {"id": "content", "type": "textarea", "label": "그림 설명", "rows": 2, "default": "a girl, full body",
     "hint": "그림에 무엇이 있는지 짧게 써요. 처음 그릴 때 쓴 설명을 그대로 넣으면 가장 좋아요. 한글도 돼요."},
    {"id": "style", "type": "textarea", "label": "그림체 단어", "advanced": True,
     "default": "anime style, clean lineart, flat colors, cel shading, highly detailed, sharp focus",
     "targets": [{"node": "3", "input": "text", "template": "{content}, {style}"}]},
    {"id": "negative", "type": "textarea", "label": "피할 것 (부정 프롬프트)", "advanced": True, "default": NEG,
     "hint": NEG_HINT, "targets": [{"node": "4", "input": "text"}]},
    {"id": "amount", "type": "number", "label": "얼마나 다듬을지 (조금 ~ 많이)", "default": 0.35, "min": 0.15, "max": 0.7, "step": 0.05,
     "targets": [{"node": "6", "input": "denoise"}],
     "hint": "0.25 는 거의 그대로 또렷하게만, 0.35 는 질감과 세부를 다시, 0.5 이상이면 얼굴·옷 모양도 바뀌기 시작해요."},
    {"id": "size", "type": "choice", "label": "크기", "default": "1mp", "options": [
      {"value": "1mp", "label": "1024급 (고품질, 느림)", "set": [{"node": "30", "input": "megapixels", "value": 1.0}]},
      {"value": "06mp", "label": "800급 (조금 빠름)", "set": [{"node": "30", "input": "megapixels", "value": 0.6}]}],
     "hint": "그림 비율은 그대로 두고 전체 픽셀 수만 맞춰요."},
    {"id": "model", "type": "choice", "label": "SDXL 모델", "default": "turbo", "advanced": True, "options": [
      {"value": "turbo", "label": "DreamShaper XL Turbo (빠름, 8단계)",
       "set": [{"node": "2", "input": "ckpt_name", "value": TURBO}] + ks(steps=8, cfg=2.0, sampler_name="dpmpp_sde", scheduler="karras")},
      {"value": "base", "label": "SDXL 기본 1.0 (느림, 25단계)",
       "set": [{"node": "2", "input": "ckpt_name", "value": BASE}] + ks(steps=25, cfg=6.0, sampler_name="dpmpp_2m", scheduler="karras")}],
     "hint": "설치 안내의 'SDXL 모델 준비'에서 받은 모델을 골라요. 보통은 Turbo 만 있으면 돼요."},
    {"id": "rembg", "type": "toggle", "label": "배경 제거한 그림도 만들기", "default": False,
     "bypass_off": [{"node": "12", "input": "images"}]},
    palette_field(), seed_field("6")],
  "outputs": [{"node": "8", "label": "고품질"}, {"node": "12", "label": "투명"}],
  "postprocess": palette_step(["8", "12"])})

# LoRA 칸: SD 1.5 로 그리는 탭에 모두 (SDXL 탭은 SD 1.5 LoRA 가 안 맞아서 뺀다). 글자칸 뒤, 팔레트·시드 앞에 둔다.
for pid, (w, cfg) in presets.items():
    if pid == "11_sdxl" or not any(v["class_type"] == "CheckpointLoaderSimple" for v in w.values()):
        continue
    pos = "6" if "_fix_" in pid else "3"
    lf = {"id": "loras", "type": "loras", "label": "LoRA (캐릭터·그림체)", "prompt_targets": [{"node": pos, "input": "text"}],
          "hint": "ComfyUI\\models\\loras 폴더의 LoRA 를 골라요. 여러 개를 같이 써도 돼요. 세기는 0.6~1.0 이 무난해요."}
    fl = cfg["fields"]
    at = next((i for i, f in enumerate(fl) if f["type"] in ("palette", "seed") or f["id"] in ("hires", "pixel")), len(fl))
    fl.insert(at, lf)

# 미리보기(확인용)만 다른 기능으로 보내지 않는다. 투명 그림도 보낼 수 있다 (도트 만들기 등).
for pid, (w, cfg) in presets.items():
    for o in cfg["outputs"]:
        o.pop("send", None)
        if "확인" in o["label"]:
            o["send"] = False

# 도구 탭 (워크플로 없음, 화면은 web/<tool>.js)
d = os.path.join(OUT, "03p_pose3d"); os.makedirs(d)
json.dump({"name": "3D 자세 만들기", "group": "그리기", "order": 3.5, "tool": "pose3d", "fields": [],
           "description": "3D 뼈대의 관절을 끌어서 자세를 잡고, 뼈대 그림으로 '자세 참고 캐릭터'나 '스프라이트 애니메이션'에 보내요."},
          open(os.path.join(d, "preset.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

for pid, (w, cfg) in presets.items():
    d = os.path.join(OUT, pid); os.makedirs(d)
    cfg["workflow"] = "workflow_api.json"
    json.dump(w, open(os.path.join(d, "workflow_api.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(cfg, open(os.path.join(d, "preset.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 설정이 가리키는 노드/입력이 실제로 있는지 확인
    for f in cfg["fields"]:
        tg = f.get("targets", []) + [s for o in f.get("options", []) for s in o.get("set", [])]
        for t in tg:
            assert t["input"] in w[t["node"]]["inputs"], (pid, t)
        for t in f.get("bypass_off", []) + f.get("bypass_on", []) + f.get("bypass_empty", []):
            ins = t["input"].values() if isinstance(t["input"], dict) else [t["input"]]
            assert all(i in w[t["node"]]["inputs"] for i in ins), (pid, t)
    for st in cfg.get("postprocess", []):
        for n in st["from_node"]:
            assert any(o["node"] == n for o in cfg["outputs"]), (pid, n)
    for o in cfg["outputs"]:
        assert w[o["node"]]["class_type"] in ("SaveImage", "PreviewImage"), (pid, o)
    print("ok", pid)
