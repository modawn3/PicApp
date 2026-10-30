"""그림 도구 자동 업데이트.

GitHub 저장소(설정 "update_repo": "아이디/저장소이름")의 최신 판을 받아 PicApp 폴더를 바꾼다.
- 내가 만든 것(settings.json, 번역사전.txt, palettes, poses, results, models)은 그대로 둔다.
  번역사전.txt 는 새 판에 생긴 줄만 덧붙인다.
- 바뀌거나 지워지는 파일은 backup/<시각>/ 에 먼저 옮겨 둔다.
- 비공개 저장소면 settings.json 의 "update_token" 에 읽기 전용 토큰을 넣는다.

그림 도구 화면의 '업데이트' 버튼, 또는 업데이트.bat (= python updater.py) 으로 쓴다.
"""
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(APP_DIR, ".update_state.json")
BACKUP_DIR = os.path.join(APP_DIR, "backup")
# 업데이트가 손대지 않는 폴더 (사용자가 만든 것, 받은 모델, 결과)
SKIP_DIRS = ("results/", "models/", "backup/", "poses/", "__pycache__/")
# 이미 있으면 그대로 두는 파일 (새 판에만 있는 것은 새로 넣는다)
KEEP_FILES = ("settings.json", "번역사전.txt")
KEEP_DIRS = ("palettes/",)
DICT_FILE = "번역사전.txt"


class UpdateError(Exception):
    pass


def _settings():
    s = {"update_repo": "", "update_branch": "main", "update_token": "", "update_dir": "PicApp",
         "update_api": "https://api.github.com"}  # update_api 는 시험용으로만 바꾼다
    path = os.path.join(APP_DIR, "settings.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if v not in (None, "")})
    # server.py 의 기본값(DEFAULT_SETTINGS)에 저장소가 적혀 있으면 그것을 쓴다
    if not s["update_repo"]:
        try:
            src = open(os.path.join(APP_DIR, "server.py"), encoding="utf-8").read()
            m = re.search(r'"update_repo":\s*"([^"]+)"', src)
            if m:
                s["update_repo"] = m.group(1)
        except OSError:
            pass
    return s


def _state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _get(url, s, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "PicApp-updater", "Accept": "application/vnd.github+json"})
    if s.get("update_token"):
        req.add_header("Authorization", "Bearer " + s["update_token"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and s.get("update_token"):
            raise UpdateError("GitHub 토큰이 맞지 않거나 기간이 끝났어요. settings.json 의 update_token 을 확인하세요.")
        if e.code == 404:
            raise UpdateError(f"저장소 {s['update_repo']} 를 찾지 못했어요. 비공개 저장소면 토큰이 필요해요.")
        if e.code == 403:
            raise UpdateError("GitHub 확인을 너무 자주 했어요. 한 시간쯤 뒤에 다시 해 보세요.")
        raise UpdateError(f"GitHub 응답 오류 {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"인터넷에 연결하지 못했어요 ({getattr(e, 'reason', e)}).")


def configured():
    return bool(_settings()["update_repo"])


def check():
    """{"available": bool, "current": sha|None, "latest": sha, "changes": [설명...], "date": "..."}"""
    s = _settings()
    if not s["update_repo"]:
        return {"configured": False, "available": False}
    api = f"{s['update_api']}/repos/{s['update_repo']}"
    head = json.loads(_get(f"{api}/commits/{s['update_branch']}", s))
    latest = head["sha"]
    cur = _state().get("sha")
    changes = []
    if cur and cur != latest:
        try:
            cmp = json.loads(_get(f"{api}/compare/{cur}...{latest}", s))
            changes = [c["commit"]["message"].split("\n")[0] for c in cmp.get("commits", [])]
        except UpdateError:
            pass
    if not changes and cur != latest:
        changes = [head["commit"]["message"].split("\n")[0]]
    return {"configured": True, "available": cur != latest, "current": cur, "latest": latest,
            "date": head["commit"]["committer"]["date"], "changes": changes[-15:][::-1]}


def _members(zf, sub):
    """zip 안의 PicApp 파일들: {상대경로: zip 안 이름}"""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    top = names[0].split("/")[0] + "/" if names else ""
    for prefix in (top + sub.strip("/") + "/", top):
        if prefix + "server.py" in names:
            return {n[len(prefix):]: n for n in names if n.startswith(prefix)}
    raise UpdateError("받은 파일 안에서 그림 도구(server.py)를 찾지 못했어요.")


def _merge_dict(old, new):
    """번역사전: 내 줄은 그대로, 새 판에만 있는 한글 단어 줄을 끝에 덧붙인다."""
    have = {ln.split("=", 1)[0].strip() for ln in old.splitlines() if "=" in ln and not ln.lstrip().startswith("#")}
    add = [ln for ln in new.splitlines()
           if "=" in ln and not ln.lstrip().startswith("#") and ln.split("=", 1)[0].strip() not in have]
    if not add:
        return None
    return old.rstrip("\n") + "\n\n# 업데이트로 추가된 단어 (" + time.strftime("%Y-%m-%d") + ")\n" + "\n".join(add) + "\n"


def apply(log=print):
    """최신 판을 받아 설치. 바뀐 파일 수 등을 돌려준다."""
    s = _settings()
    if not s["update_repo"]:
        raise UpdateError("업데이트 받을 곳(update_repo)이 아직 정해지지 않았어요.")
    info = check()
    if not info["available"]:
        return {"changed": 0, "message": "이미 최신이에요."}
    log("새 판을 받는 중…")
    data = _get(f"{s['update_api']}/repos/{s['update_repo']}/zipball/{info['latest']}", s, timeout=120)
    zf = zipfile.ZipFile(io.BytesIO(data))
    files = _members(zf, s["update_dir"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR, stamp)
    changed, added, removed = [], [], []

    def keep_aside(rel):
        dst = os.path.join(backup, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(APP_DIR, rel), dst)

    def write(rel, content):
        path = os.path.join(APP_DIR, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".new"
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, path)

    for rel, name in sorted(files.items()):
        if rel.startswith(SKIP_DIRS) or rel == os.path.basename(STATE_PATH) or ".." in rel.split("/"):
            continue
        content = zf.read(name)
        path = os.path.join(APP_DIR, rel)
        exists = os.path.isfile(path)
        if exists and rel == DICT_FILE:
            old = open(path, encoding="utf-8-sig").read()
            merged = _merge_dict(old, content.decode("utf-8-sig"))
            if merged:
                keep_aside(rel)
                write(rel, merged.encode("utf-8"))
                changed.append(rel)
            continue
        if exists and (rel in KEEP_FILES or rel.startswith(KEEP_DIRS)):
            continue
        if exists:
            with open(path, "rb") as f:
                if f.read() == content:
                    continue
            keep_aside(rel)
            changed.append(rel)
        else:
            added.append(rel)
        write(rel, content)

    # 예전 판에는 있었는데 새 판에서 빠진 파일은 backup 으로 옮긴다 (내가 만든 것은 건드리지 않음)
    new_set = set(files)
    for rel in _state().get("files", []):
        if rel in new_set or rel.startswith(SKIP_DIRS + KEEP_DIRS) or rel in KEEP_FILES:
            continue
        path = os.path.join(APP_DIR, rel)
        if os.path.isfile(path):
            keep_aside(rel)
            os.remove(path)
            removed.append(rel)
            d = os.path.dirname(path)  # 비게 된 폴더도 지운다 (빈 프리셋 폴더가 탭으로 남지 않게)
            while d != APP_DIR and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)

    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"sha": info["latest"], "date": info["date"], "installed": stamp, "files": sorted(new_set)},
                  f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)
    n = len(changed) + len(added) + len(removed)
    log(f"바뀐 파일 {len(changed)}개, 새 파일 {len(added)}개, 뺀 파일 {len(removed)}개")
    if n:
        log(f"예전 파일은 backup\\{stamp} 에 있어요.")
    return {"changed": n, "changes": info["changes"], "backup": stamp if n else None,
            "message": "업데이트했어요." if n else "받은 판이 지금과 같았어요."}


def main():
    print("=== 그림 도구 업데이트 ===")
    try:
        info = check()
        if not info["configured"]:
            print("업데이트 받을 곳이 아직 정해지지 않았어요. (settings.json 의 update_repo)")
            return 1
        if not info["available"]:
            print("이미 최신이에요.")
            return 0
        print("새로 바뀐 것:")
        for c in info["changes"]:
            print("  -", c)
        r = apply()
        print(r["message"])
        print("그림 도구 검은 창이 켜져 있으면 닫고 그림도구_실행.bat 을 다시 켜세요.")
        return 0
    except UpdateError as e:
        print("업데이트하지 못했어요:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
