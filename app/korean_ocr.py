"""윈도우에 기본으로 들어 있는 글자 인식(OCR)으로 한국어 대화방 이름을 읽는 부분.

윈도우 기본 프로그램인 PowerShell 을 잠깐 실행해서 읽습니다.
(번역기 안의 중국어 글자 인식과 같은 프로그램 안에서 함께 불러오면 충돌하기 때문에 따로 실행)
쓸 수 없는 환경이면 None 을 돌려주고, 프로그램은 제목 모양으로 대화방을 구분합니다.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import tempfile

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:MANOS_OCR_IMG)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($env:MANOS_OCR_LANG))
if ($null -eq $engine) { exit 2 }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$stream.Dispose()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output $result.Text
"""

_disabled = False


def read_text(img, lang: str = "ko", timeout: float = 20) -> str | None:
    """그림 속 글자를 윈도우 글자 인식으로 읽음 (실패하면 None)."""
    global _disabled
    if sys.platform != "win32" or _disabled:
        return None
    fd, path = tempfile.mkstemp(suffix=".png", prefix="manos_title_")
    os.close(fd)
    try:
        img.convert("RGB").save(path)
        env = dict(os.environ, MANOS_OCR_IMG=path, MANOS_OCR_LANG=lang)
        encoded = base64.b64encode(PS_SCRIPT.encode("utf-16-le")).decode("ascii")
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            env=env, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode == 2:  # 이 언어의 글자 인식이 설치되어 있지 않음
            _disabled = True
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", "replace").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def clean_title(text: str | None) -> str:
    """대화방 제목 정리: 줄바꿈·인원수 표시·앞뒤 기호 제거."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*[(（]\d+[)）]\s*$", "", text)
    return text.strip(" .·-_|")
