"""설정과 저장 위치 관리.

모든 데이터는 이 컴퓨터 안에만 저장됩니다.
Windows: %APPDATA%\\ManosWeChatTranslator
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

APP_NAME = "ManosWeChatTranslator"

CONFIG_VERSION = 3
# 화면 인식 관련 값은 버전이 바뀌면 새 기본값으로 다시 맞춤
LAYOUT_KEYS = ("chat_left_ratio", "title_height", "input_height", "ocr_min_score", "ocr_min_height")

DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "api_key": "",
    "model": "claude-sonnet-5-5",
    "effort": "low",
    "tone": "polite",
    # 위챗 옆에 자동으로 붙기
    "dock": True,
    # 위챗 화면을 읽어서 업체 메시지 자동 번역 (위챗을 조작하지 않고 화면만 읽음)
    "auto_read": True,
    # 업체 중국어를 Ctrl+C 하면 자동 번역 (자동 읽기가 실패할 때를 위한 보조 기능)
    "clipboard_watch": True,
    "panel_width": 400,
    "poll_seconds": 1.5,
    # 위챗 창 안에서 '대화 영역'의 위치 (위챗 창 기준, 픽셀). 화면에 맞춰 조정 가능.
    # (0 = 자동. 대화 영역 왼쪽 끝은 대화방 목록의 날짜 위치로 자동으로 찾고, 못 찾으면 이 비율 사용)
    "chat_left_ratio": 0.41,
    "title_height": 0,
    "input_height": 0,
    "ocr_min_score": 0.5,
    "ocr_min_height": 12,
    # 한국어 메모 이름처럼 글자로 못 읽는 대화방 제목 → 대표님이 정한 거래처 이름
    "title_map": [],
    "max_new_per_scan": 3,
    "history_for_prompt": 12,
    "quick_phrases": [
        "단가 확인 부탁드립니다",
        "출고일 알려주세요",
        "샘플 먼저 보내주세요",
        "불량품 교환 요청합니다",
        "송장번호 보내주세요",
        "결제했습니다. 확인 부탁드립니다",
    ],
}


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "history").mkdir(exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def instructions_path() -> Path:
    p = data_dir() / "instructions.txt"
    if not p.exists():
        p.write_text(
            "# 여기에 대표님만의 지시문·용어를 적어 주세요. (# 으로 시작하는 줄은 무시됩니다)\n"
            "# 예) 우리 회사 이름은 구름콩방입니다.\n"
            "# 예) '박스 파손'은 外箱破损 으로 번역\n",
            encoding="utf-8",
        )
    return p


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if saved.get("config_version", 1) < CONFIG_VERSION:
                for k in LAYOUT_KEYS:
                    saved.pop(k, None)
                saved["config_version"] = CONFIG_VERSION
            cfg.update(saved)
        except (OSError, ValueError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_user_instructions() -> str:
    lines = instructions_path().read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if l.strip() and not l.lstrip().startswith("#"))


def _safe_name(vendor: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", vendor).strip("_")
    return name[:60] or "unknown"


def load_history(vendor: str) -> list[dict]:
    p = data_dir() / "history" / f"{_safe_name(vendor)}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []


def save_history(vendor: str, history: list[dict]) -> None:
    p = data_dir() / "history" / f"{_safe_name(vendor)}.json"
    p.write_text(json.dumps(history[-500:], ensure_ascii=False, indent=1), encoding="utf-8")
