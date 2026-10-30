"""다른 기기(노트북, 휴대폰)에서 그림 도구를 쓰게 하는 원격 접속.

기본은 꺼져 있다. 켜면 그림 도구가 이 컴퓨터 밖에서도 접속을 받지만
- Tailscale(내 기기끼리만 통하는 개인 네트워크) 주소에서 온 접속만 받고 (설정 "remote_allow": "lan" 이면 같은 와이파이도)
- 이 컴퓨터가 아닌 곳에서 오면 비밀번호를 물어본다.
인터넷 전체에 그림 도구를 여는 공유기 포트 포워딩은 쓰지 않는다.

설정은 원격접속_설정.bat (= python remote.py --setup) 으로 한다.
"""
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
COOKIE = "picapp_auth"
TAILSCALE = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]
# 다른 기기에서 눌러도 집 컴퓨터 화면에서만 열리는 기능
LOCAL_ONLY = {"/api/open-folder", "/api/aseprite/open", "/api/aseprite/import"}
FIREWALL_RULE = "PicApp remote access"  # 영어: 명령 창 글자 깨짐 방지

_fails = {}  # ip -> [실패 횟수, 처음 실패 시각]
_lock = threading.Lock()


# ---------- 설정 ----------

def enabled(settings):
    return bool(settings.get("remote")) and bool(settings.get("remote_password_hash"))


def bind_host(settings):
    return "0.0.0.0" if enabled(settings) else "127.0.0.1"


def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode(), 200_000).hex()


def check_password(pw, stored):
    salt, _, _ = (stored or "").partition("$")
    return bool(salt) and hmac.compare_digest(hash_password(pw, salt), stored)


def _token(settings):
    # 비밀번호를 바꾸면 예전 로그인은 저절로 풀린다
    return hmac.new(settings["remote_password_hash"].encode(), b"picapp-login", "sha256").hexdigest()


# ---------- 누가 접속했나 ----------

def client_ip(handler):
    ip = ipaddress.ip_address(handler.client_address[0])
    return getattr(ip, "ipv4_mapped", None) or ip


def is_remote(handler):
    return not client_ip(handler).is_loopback


def _allowed(ip, settings):
    if ip.is_loopback or any(ip in n for n in TAILSCALE):
        return True
    return settings.get("remote_allow") == "lan" and ip.is_private


def _logged_in(handler, settings):
    for part in (handler.headers.get("Cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and hmac.compare_digest(v, _token(settings)):
            return True
    return False


def gate(handler, settings, path):
    """요청을 처리해도 되면 True. 안 되면 알맞은 응답을 이미 보내고 False."""
    # 다른 웹사이트가 몰래 그림 도구로 요청을 보내는 것을 막는다
    origin = handler.headers.get("Origin")
    if origin and origin != "null" and urllib.parse.urlparse(origin).netloc != handler.headers.get("Host"):
        handler.send(403, {"error": "다른 사이트에서 온 요청이라 막았어요."})
        return False
    if not is_remote(handler):
        return True
    ip = client_ip(handler)
    if not enabled(settings) or not _allowed(ip, settings):
        handler.send(403, {"error": "이 주소에서는 그림 도구에 들어올 수 없어요."})
        return False
    if path == "/api/login":
        return _login(handler, settings, ip)
    if not _logged_in(handler, settings):
        if path.startswith("/api/"):
            handler.send(401, {"error": "로그인이 필요해요. 페이지를 새로 고치세요."})
        else:
            handler.send(200, LOGIN_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        return False
    if path in LOCAL_ONLY:
        handler.send(400, {"error": "이 기능은 집 컴퓨터 앞에서만 돼요. 그림은 '저장' 버튼으로 받으세요."})
        return False
    return True


def _login(handler, settings, ip):
    key = str(ip)
    with _lock:
        n, since = _fails.get(key, (0, time.time()))
        if time.time() - since > 600:
            n, since = 0, time.time()
    if n >= 10:
        handler.send(429, {"error": "비밀번호를 너무 많이 틀렸어요. 10분 뒤에 다시 해 보세요."})
        return False
    length = int(handler.headers.get("Content-Length", 0))
    try:
        pw = json.loads(handler.rfile.read(length) or b"{}").get("password", "")
    except ValueError:
        pw = ""
    if not check_password(pw, settings["remote_password_hash"]):
        with _lock:
            _fails[key] = (n + 1, since)
        time.sleep(1)
        handler.send(401, {"error": "비밀번호가 달라요."})
        return False
    with _lock:
        _fails.pop(key, None)
    body = b'{"ok": true}'
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Set-Cookie", f"{COOKIE}={_token(settings)}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict")
    handler.end_headers()
    handler.wfile.write(body)
    return False


LOGIN_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>그림 도구 로그인</title>
<style>
body { font-family: system-ui, sans-serif; background: #f5f5f7; color: #222; display: grid; place-items: center; min-height: 100vh; margin: 0; }
form { background: #fff; padding: 28px; border-radius: 12px; box-shadow: 0 2px 12px #0001; width: min(320px, 90vw); }
h1 { font-size: 20px; margin: 0 0 8px; } p { color: #666; font-size: 14px; margin: 0 0 16px; }
input, button { width: 100%; box-sizing: border-box; font-size: 16px; padding: 10px; border-radius: 8px; border: 1px solid #ccc; }
button { margin-top: 10px; background: #4b5cc4; color: #fff; border: 0; cursor: pointer; }
#err { color: #c33; font-size: 14px; min-height: 1.2em; margin-top: 8px; }
@media (prefers-color-scheme: dark) { body { background: #1b1b1f; color: #eee; } form { background: #26262c; } input { background: #1b1b1f; color: #eee; border-color: #444; } }
</style></head><body>
<form id="f"><h1>그림 도구</h1><p>집 컴퓨터의 그림 도구에 들어가요.</p>
<input id="pw" type="password" placeholder="원격 접속 비밀번호" autofocus autocomplete="current-password">
<button>들어가기</button><div id="err"></div></form>
<script>
document.getElementById("f").onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: document.getElementById("pw").value }) });
  if (r.ok) location.reload();
  else document.getElementById("err").textContent = (await r.json().catch(() => ({}))).error || "들어가지 못했어요.";
};
</script></body></html>"""


# ---------- 켤 때 주소 안내 ----------

def _tailscale_exe():
    for p in (shutil.which("tailscale"), r"C:\Program Files\Tailscale\tailscale.exe"):
        if p and os.path.isfile(p):
            return p
    return None


def tailscale_addresses():
    """[(설명, 주소)] Tailscale 이름과 IP. 못 찾으면 빈 목록."""
    out = []
    exe = _tailscale_exe()
    if exe:
        try:
            st = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, timeout=5).stdout)
            name = (st.get("Self") or {}).get("DNSName", "").rstrip(".")
            if name:
                out.append(name)
            out += [a for a in (st.get("Self") or {}).get("TailscaleIPs", []) if ":" not in a]
        except Exception:
            pass
    if not out:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if ipaddress.ip_address(ip) in TAILSCALE[0] and ip not in out:
                    out.append(ip)
        except OSError:
            pass
    return out


def print_addresses(settings, port):
    if settings.get("remote") and not settings.get("remote_password_hash"):
        print("원격 접속이 켜져 있지만 비밀번호가 없어서 이 컴퓨터에서만 열었어요. 원격접속_설정.bat 을 실행하세요.")
        return
    if not enabled(settings):
        return
    addrs = tailscale_addresses()
    if addrs:
        print("다른 기기(Tailscale 켜 둔 것)에서는 이 주소로 들어오세요:")
        for a in addrs:
            print(f"    http://{a}:{port}")
    else:
        print("원격 접속은 켜져 있지만 Tailscale 주소를 찾지 못했어요. Tailscale 이 켜져 있고 로그인했는지 확인하세요.")
    if settings.get("remote_allow") == "lan":
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as so:
                so.connect(("8.8.8.8", 80))  # 실제로 보내지는 않고, 바깥으로 나가는 쪽 주소만 알아낸다
                print(f"같은 와이파이에서는: http://{so.getsockname()[0]}:{port}")
        except OSError:
            pass
    print("이 컴퓨터가 잠자기에 들어가면 접속이 끊겨요.")


# ---------- 설정 도구 (원격접속_설정.bat) ----------

def _load():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(s):
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def _firewall(port, allow, on):
    """Windows 방화벽에 그림 도구 포트를 Tailscale(또는 같은 와이파이)에서만 여는 규칙. 관리자 권한 창이 뜬다."""
    if os.name != "nt":
        return
    cmds = [f'netsh advfirewall firewall delete rule name="{FIREWALL_RULE}"']
    if on:
        remote = "LocalSubnet,100.64.0.0/10" if allow == "lan" else "100.64.0.0/10"
        cmds.append(f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
                    f'protocol=TCP localport={port} remoteip={remote} profile=any')
    script = " & ".join(cmds)
    print("방화벽 규칙을 바꾸려고 관리자 확인 창을 띄워요. '예' 를 눌러 주세요.")
    ps = ("Start-Process cmd -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '/c " + script.replace("'", "''") + "'")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps])
    if r.returncode != 0:
        print("방화벽 규칙을 바꾸지 못했어요. (확인 창에서 '아니요' 를 눌렀다면 다시 실행하세요)")


def setup():
    s = _load()
    port = int(s.get("port", 8190))
    print("=== 그림 도구 원격 접속 설정 ===")
    print("지금:", "켜짐" if enabled(s) else "꺼짐")
    print()
    print("1. 켜기 (Tailscale 로 연결한 내 기기에서만)")
    print("2. 켜기 (Tailscale + 같은 와이파이의 기기도)")
    print("3. 끄기")
    print("4. 비밀번호만 바꾸기")
    choice = input("번호를 고르세요: ").strip()
    if choice == "3":
        s["remote"] = False
        _save(s)
        _firewall(port, s.get("remote_allow"), False)
        print("원격 접속을 껐어요.")
        return
    if choice not in ("1", "2", "4"):
        print("취소했어요.")
        return
    import getpass
    while True:
        pw = getpass.getpass("원격 접속 비밀번호 (6글자 이상, 입력해도 화면에 안 보여요): ")
        if len(pw) < 6:
            print("6글자 이상으로 해 주세요.")
            continue
        if getpass.getpass("한 번 더: ") != pw:
            print("두 번 입력한 것이 달라요.")
            continue
        break
    s["remote_password_hash"] = hash_password(pw)
    if choice in ("1", "2"):
        s["remote"] = True
        s["remote_allow"] = "lan" if choice == "2" else "tailscale"
        _save(s)
        _firewall(port, s["remote_allow"], True)
    else:
        _save(s)
    print()
    print("저장했어요. 그림 도구 검은 창이 켜져 있으면 닫고 그림도구_실행.bat 을 다시 켜세요.")
    addrs = tailscale_addresses()
    if addrs:
        print(f"다른 기기에서는 http://{addrs[0]}:{port} 로 들어오면 돼요.")
    else:
        print("Tailscale 을 아직 설치하지 않았다면 설치_안내.md 의 '다른 기기에서 쓰기' 를 따라 하세요.")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        try:
            setup()
        except (KeyboardInterrupt, EOFError):
            print("\n취소했어요.")
