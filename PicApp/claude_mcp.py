"""Claude 연결 장치 (MCP 서버).

Claude 데스크톱 앱이 이 파일을 켜서 그림 도구를 쓴다. 등록은 Claude_연결_설정.bat 으로 한 번만 한다.
여기는 Claude 와 주고받는 규칙(MCP, 표준 입출력 JSON-RPC)만 있고, 실제 기능은 claude_tools.py 에 있다.
claude_tools.py 는 바뀌면 저절로 다시 읽으므로 업데이트 뒤 Claude 를 다시 켜지 않아도 된다.

    python claude_mcp.py            Claude 가 켜는 방법 (사람이 직접 켤 일은 없음)
    python claude_mcp.py --install  Claude 데스크톱 앱에 등록
    python claude_mcp.py --remove   등록 지우기
"""
import glob
import importlib
import json
import os
import shutil
import sys
import threading
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
SERVER_NAME = "picapp"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")


def log(*args):
    print(*args, file=sys.stderr, flush=True)


# ---------- 기능 모듈 (바뀌면 다시 읽기) ----------

_tools = {"mod": None, "mtime": None}
_tools_lock = threading.Lock()


def tools():
    with _tools_lock:
        return _load_tools()


def _load_tools():
    path = os.path.join(APP_DIR, "claude_tools.py")
    mtime = os.path.getmtime(path)
    if _tools["mod"] is None:
        _tools["mod"] = importlib.import_module("claude_tools")
    elif mtime != _tools["mtime"]:
        try:
            _tools["mod"] = importlib.reload(_tools["mod"])
            log("claude_tools.py 를 새로 읽었어요.")
        except Exception:  # 고치는 중에 깨진 파일이면 예전 것을 계속 쓴다
            log(traceback.format_exc())
    _tools["mtime"] = mtime
    return _tools["mod"]


# ---------- MCP (표준 입출력, 한 줄에 JSON 하나) ----------

_out = sys.stdout.buffer
_out_lock = threading.Lock()  # 도구마다 따로 돌아서 한 줄씩 차례로 쓴다


def send(msg):
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"
    with _out_lock:
        _out.write(data)
        _out.flush()


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    send(msg)


def handle(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        t = tools()
        return reply(mid, {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "그림 도구", "version": t.version()},
            "instructions": t.INSTRUCTIONS,
        })
    if method == "ping":
        return reply(mid, {})
    if method == "tools/list":
        return reply(mid, {"tools": tools().tool_list()})
    if method == "tools/call":
        token = (params.get("_meta") or {}).get("progressToken")

        count = [0]

        def progress(message=""):  # 진행 상황 알림 (Claude 가 기다리는 시간도 늘어난다)
            if token is None:
                return
            count[0] += 1
            send({"jsonrpc": "2.0", "method": "notifications/progress",
                  "params": {"progressToken": token, "progress": count[0], "message": message}})

        try:
            result = tools().call(params.get("name"), params.get("arguments") or {}, progress)
        except Exception as e:
            log(traceback.format_exc())
            result = {"content": [{"type": "text", "text": f"오류: {e}"}], "isError": True}
        return reply(mid, result)
    if mid is not None:  # 모르는 요청 (알림은 대답하지 않는다)
        reply(mid, error={"code": -32601, "message": f"지원하지 않는 요청: {method}"})


def serve():
    log(f"그림 도구 연결 장치를 켰어요 ({APP_DIR})")
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            reply(None, error={"code": -32700, "message": "JSON 이 아니에요"})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            if isinstance(m, dict) and m.get("method") == "tools/call":
                # 오래 걸리는 도구가 다른 요청(목록, 상태 확인)을 막지 않게 따로 돌린다
                threading.Thread(target=handle, args=(m,), daemon=True).start()
            elif isinstance(m, dict) and "method" in m:
                handle(m)


# ---------- Claude 데스크톱 앱에 등록 ----------

def config_paths():
    """Claude 데스크톱 앱 설정 파일 후보. 설치 방식(일반/스토어)에 따라 자리가 다르다."""
    out = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")
        out.append(os.path.join(appdata, "Claude"))
        out += glob.glob(os.path.join(local, "Packages", "Claude_*", "LocalCache", "Roaming", "Claude"))
    elif sys.platform == "darwin":
        out.append(os.path.expanduser("~/Library/Application Support/Claude"))
    else:
        out.append(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "Claude"))
    found = [d for d in out if os.path.isdir(d)]
    return [os.path.join(d, "claude_desktop_config.json") for d in (found or out[:1])]


def edit_config(path, entry):
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
        if text.strip():
            cfg = json.loads(text)
        shutil.copy2(path, path + ".bak")
    servers = cfg.setdefault("mcpServers", {})
    if entry is None:
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def install(remove=False):
    me = os.path.abspath(__file__)
    py = os.path.normpath(sys.executable)
    entry = None if remove else {"command": py, "args": ["-s", me]}
    ok = 0
    for path in config_paths():
        try:
            edit_config(path, entry)
            print(("등록을 지웠어요: " if remove else "등록했어요: ") + path)
            ok += 1
        except ValueError:
            print("설정 파일이 깨져 있어서 고치지 못했어요:", path)
            print("  메모장으로 열어 내용을 지우고 다시 해 보세요.")
        except OSError as e:
            print("설정 파일을 쓰지 못했어요:", path, e)
    if not ok:
        return 1
    print()
    print("이제 Claude 데스크톱 앱을 완전히 껐다 켜 주세요.")
    print("  (창만 닫으면 안 꺼져요. 화면 오른쪽 아래 트레이의 Claude 아이콘 → 오른쪽 클릭 → 종료)")
    if not remove:
        print("다시 켠 뒤 '그림 도구로 고양이 캐릭터 그려줘' 처럼 말하면 돼요.")
        print()
        print("Claude Code(명령줄)에서도 쓰려면 이 줄을 한 번 실행하세요:")
        print(f'  claude mcp add {SERVER_NAME} --scope user -- "{py}" -s "{me}"')
    return 0


def setup_menu():
    print("Claude 데스크톱 앱에 그림 도구를 연결해요.")
    print("  1 = 연결하기 (처음 한 번)")
    print("  2 = 연결 끊기")
    choice = input("번호를 누르고 Enter: ").strip()
    if choice == "2":
        return install(remove=True)
    if choice in ("1", ""):
        return install()
    print("1 이나 2 를 눌러 주세요.")
    return 1


if __name__ == "__main__":
    if "--install" in sys.argv:
        sys.exit(install())
    if "--remove" in sys.argv:
        sys.exit(install(remove=True))
    if "--setup" in sys.argv:
        sys.exit(setup_menu())
    serve()
