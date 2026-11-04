"""바로가기 정리: 켤 때마다 바탕화면·시작 메뉴 바로가기를 '바로통' 이름과 새 아이콘으로 맞추고, 윈도우 아이콘 그림 기억을 새로 고침."""
from __future__ import annotations

import base64
import os
import subprocess
import sys

PS = r"""
$exe = $env:MANOS_EXE
$shell = New-Object -ComObject WScript.Shell
$global:changed = $false
$desk = [Environment]::GetFolderPath('Desktop')
$progs = [Environment]::GetFolderPath('Programs')

function Fix($p) {
  if (Test-Path -LiteralPath $p) {
    $s = $shell.CreateShortcut($p)
    if ($s.IconLocation -ne "$exe,0") { $s.IconLocation = "$exe,0"; $s.Save(); $global:changed = $true }
  }
}

# 바탕화면: '위챗+번역기' → '바로통' (이미 있으면 예전 것만 지움)
$old = Join-Path $desk '위챗+번역기.lnk'
$new = Join-Path $desk '바로통.lnk'
if (Test-Path -LiteralPath $old) {
  if (Test-Path -LiteralPath $new) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
  else { Rename-Item -LiteralPath $old -NewName '바로통.lnk' -Force -ErrorAction SilentlyContinue }
  $global:changed = $true
}
Fix $new

# 시작 메뉴: '발주 번역기' 폴더 → '바로통' 폴더
$oldDir = Join-Path $progs '발주 번역기'
$newDir = Join-Path $progs '바로통'
if (Test-Path -LiteralPath $oldDir) {
  if (Test-Path -LiteralPath $newDir) {
    Get-ChildItem -LiteralPath $oldDir | ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $newDir -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $oldDir -Recurse -Force -ErrorAction SilentlyContinue
  } else {
    Rename-Item -LiteralPath $oldDir -NewName '바로통' -Force -ErrorAction SilentlyContinue
  }
  $global:changed = $true
}
$del = Join-Path $newDir '발주 번역기 삭제.lnk'
if (Test-Path -LiteralPath $del) {
  Rename-Item -LiteralPath $del -NewName '바로통 삭제.lnk' -Force -ErrorAction SilentlyContinue
  $global:changed = $true
}
Fix (Join-Path $newDir '위챗+번역기.lnk')
Fix (Join-Path $newDir '번역기만 켜기.lnk')

# 바뀐 게 있으면 윈도우가 기억하는 아이콘 그림을 새로 고침
if ($global:changed) {
  try {
    Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class ShNotify { [DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b); }'
    [ShNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
  } catch {}
  try { & ie4uinit.exe -show } catch {}
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
