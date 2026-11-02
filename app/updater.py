"""자동 업데이트: GitHub 에 올라온 새 실행 파일을 받아서 바꿔 끼우고 다시 켜는 부분."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

from .version import VERSION

REPO = "manoskpm/manos-wechat"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "ManosTranslator.exe"


def parse_version(tag: str | None) -> int | None:
    m = re.fullmatch(r"v?(\d+)", (tag or "").strip())
    return int(m.group(1)) if m else None


def current_version() -> int | None:
    return parse_version(VERSION)


def can_update() -> bool:
    """실행 파일(.exe)로 실행 중이고 버전 번호가 있을 때만 업데이트."""
    return bool(getattr(sys, "frozen", False)) and current_version() is not None and sys.platform == "win32"


def _contexts():
    """인터넷 보안 접속 방법 후보: 기본 → 윈도우 인증서 저장소(번역 기능과 같은 방식) → 내장 인증서."""
    import ssl
    yield "기본", None
    try:
        import truststore
        yield "윈도우 인증서", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    try:
        import certifi
        yield "내장 인증서", ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass


def _open(url: str, timeout: float, accept: str | None = None):
    headers = {"User-Agent": "ManosTranslator"}
    if accept:
        headers["Accept"] = accept
    errors = []
    for name, ctx in _contexts():
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                          timeout=timeout, context=ctx)
        except Exception as e:  # 다음 방법으로 다시 시도
            errors.append(f"{name}: {e}")
    raise OSError(" / ".join(errors))


def check_latest(timeout: float = 15) -> dict | None:
    """새 버전이 있으면 {"version", "url", "notes"} 를 돌려줌. 없으면 None, 확인 실패면 OSError."""
    cur = current_version()
    if cur is None:
        return None
    with _open(LATEST_URL, timeout, "application/vnd.github+json") as r:
        data = json.loads(r.read().decode("utf-8"))
    return pick_update(data, cur)


def latest_version_text(timeout: float = 15) -> str:
    with _open(LATEST_URL, timeout, "application/vnd.github+json") as r:
        return json.loads(r.read().decode("utf-8")).get("tag_name", "?")


def pick_update(release: dict, cur: int) -> dict | None:
    ver = parse_version(release.get("tag_name"))
    if ver is None or ver <= cur:
        return None
    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset:
        return None
    notes = (release.get("body") or "").strip()
    return {"version": ver, "url": asset["browser_download_url"], "notes": notes[:600]}


NEW_NAME = "ManosTranslator.new.exe"
MARK_NAME = "ManosTranslator.new.json"


def _dir() -> str:
    return os.path.dirname(sys.executable)


def download(url: str, progress=None, version: int | None = None) -> str:
    """새 실행 파일을 지금 실행 파일 옆에 받아 둠 (다 받은 뒤에만 이름을 바꿔서, 받다 끊겨도 안전).
    받은 파일 경로를 돌려줌."""
    new_path = os.path.join(_dir(), NEW_NAME)
    part = new_path + ".part"
    with _open(url, 60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done * 100 // total)
    if os.path.getsize(part) < 5_000_000 or (total and os.path.getsize(part) != total):  # 덜 받았거나 잘못 받음
        os.remove(part)
        raise OSError("업데이트 파일을 제대로 받지 못했습니다.")
    os.replace(part, new_path)
    with open(os.path.join(_dir(), MARK_NAME), "w", encoding="utf-8") as f:
        json.dump({"version": version}, f)
    return new_path


def pending_update() -> tuple[str, int] | None:
    """미리 받아 둔 새 버전이 있으면 (파일 경로, 버전). 지금 버전보다 새것일 때만."""
    if not can_update():
        return None
    new_path, mark = os.path.join(_dir(), NEW_NAME), os.path.join(_dir(), MARK_NAME)
    try:
        with open(mark, encoding="utf-8") as f:
            ver = json.load(f).get("version")
    except (OSError, ValueError):
        return None
    if not os.path.exists(new_path) or not isinstance(ver, int) or ver <= (current_version() or 0):
        for pth in (new_path, mark):   # 이미 적용됐거나 오래된 파일은 정리
            try:
                os.remove(pth)
            except OSError:
                pass
        return None
    return new_path, ver


def apply_and_restart(new_path: str, restart: bool = True, args: list | None = None) -> None:
    """프로그램이 꺼지면 새 파일로 바꿔 끼우는 작은 배치 파일을 실행 (호출 뒤 프로그램 종료 필요).
    restart=False 면 바꿔 끼우기만 하고 켜지 않음 (위챗을 꺼서 번역기가 꺼질 때)."""
    exe = sys.executable
    mark = os.path.join(_dir(), MARK_NAME)
    arg_text = " ".join(f'"{a}"' for a in (args or []))
    start = f'start "" "{exe}" {arg_text}' if restart else "rem"
    bat = os.path.join(tempfile.gettempdir(), "manos_translator_update.bat")
    with open(bat, "w", encoding="mbcs" if sys.platform == "win32" else "utf-8") as f:
        f.write(f"""@echo off
set /a tries=0
:retry
timeout /t 1 /nobreak >nul
move /y "{new_path}" "{exe}" >nul 2>&1
if not errorlevel 1 goto done
set /a tries+=1
if %tries% lss 30 goto retry
:done
del "{mark}" >nul 2>&1
{start}
del "%~f0"
""")
    # 새 번역기가 예전 번역기의 임시 폴더를 물려받지 않도록 (PyInstaller 공식 방법)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI_", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(["cmd.exe", "/c", bat], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True, env=env)
