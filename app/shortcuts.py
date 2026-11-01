"""바로가기 아이콘 정리: 예전 버전이 만든 '위챗+번역기' 바로가기의 아이콘을 번역기 아이콘으로 바꿈."""
from __future__ import annotations

import base64
import os
import subprocess
import sys

PS = r"""
$exe = $env:MANOS_EXE
$shell = New-Object -ComObject WScript.Shell
$links = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) '위챗+번역기.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) '발주 번역기\위챗+번역기.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) '발주 번역기\번역기만 켜기.lnk')
)
foreach ($p in $links) {
  if (Test-Path $p) {
    $s = $shell.CreateShortcut($p)
    if ($s.IconLocation -ne "$exe,0") { $s.IconLocation = "$exe,0"; $s.Save() }
  }
}
"""


def fix_shortcut_icons() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        encoded = base64.b64encode(PS.encode("utf-16-le")).decode("ascii")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", encoded], env=dict(os.environ, MANOS_EXE=sys.executable),
                       capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def icon_path() -> str | None:
    """실행 파일 안에 넣어 둔 아이콘 파일 위치."""
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
    p = os.path.join(base, "assets", "icon.ico")
    return p if os.path.isfile(p) else None
