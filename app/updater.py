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


def check_latest(timeout: float = 10) -> dict | None:
    """새 버전이 있으면 {"version", "url", "notes"} 를 돌려줌. 없거나 확인 실패면 None."""
    cur = current_version()
    if cur is None:
        return None
    req = urllib.request.Request(LATEST_URL, headers={
        "User-Agent": "ManosTranslator", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return pick_update(data, cur)


def pick_update(release: dict, cur: int) -> dict | None:
    ver = parse_version(release.get("tag_name"))
    if ver is None or ver <= cur:
        return None
    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset:
        return None
    notes = (release.get("body") or "").strip()
    return {"version": ver, "url": asset["browser_download_url"], "notes": notes[:600]}


def download(url: str, progress=None) -> str:
    """새 실행 파일을 지금 실행 파일 옆에 받아 둠. 받은 파일 경로를 돌려줌."""
    target_dir = os.path.dirname(sys.executable)
    new_path = os.path.join(target_dir, "ManosTranslator.new.exe")
    req = urllib.request.Request(url, headers={"User-Agent": "ManosTranslator"})
    with urllib.request.urlopen(req, timeout=60) as r, open(new_path, "wb") as f:
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
    if os.path.getsize(new_path) < 5_000_000:  # 너무 작으면 잘못 받은 것
        os.remove(new_path)
        raise OSError("업데이트 파일을 제대로 받지 못했습니다.")
    return new_path


def apply_and_restart(new_path: str) -> None:
    """프로그램이 꺼지면 새 파일로 바꿔 끼우고 다시 켜는 작은 배치 파일을 실행 (호출 뒤 프로그램 종료 필요)."""
    exe = sys.executable
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
start "" "{exe}"
del "%~f0"
""")
    subprocess.Popen(["cmd.exe", "/c", bat], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)
