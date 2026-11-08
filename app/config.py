"""설정과 저장 위치 관리.

모든 데이터는 이 컴퓨터 안에만 저장됩니다.
Windows: %APPDATA%\\ManosWeChatTranslator
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

APP_NAME = "ManosWeChatTranslator"

CONFIG_VERSION = 8
# 화면 인식 관련 값은 버전이 바뀌면 새 기본값으로 다시 맞춤
LAYOUT_KEYS = ("chat_left_ratio", "title_height", "input_height", "ocr_min_score", "ocr_min_height",
               "title_map", "known_vendors", "poll_seconds")

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
    "poll_seconds": 0.5,
    # 위챗 창 안에서 '대화 영역'의 위치 (위챗 창 기준, 픽셀). 화면에 맞춰 조정 가능.
    # (0 = 자동. 대화 영역 왼쪽 끝은 대화방 목록의 날짜 위치로 자동으로 찾고, 못 찾으면 이 비율 사용)
    "chat_left_ratio": 0.41,
    "title_height": 0,
    "input_height": 0,
    "ocr_min_score": 0.5,
    "ocr_min_height": 12,
    # 한국어 메모 이름처럼 글자로 못 읽는 대화방 제목 → 대표님이 정한 거래처 이름
    "title_map": [],
    # 대화방 이름 → 대표님이 바꾼 표시 이름
    "aliases": {},
    "known_vendors": [],
    "history_for_prompt": 6,
    # 받은 업체 글 번역만 빠른 AI 로 (보낼 문장 후보·속뜻 풀이는 기본 AI 그대로). ⚙ 설정에서 끄고 켬
    "fast_incoming": True,
    "fast_model": "claude-haiku-5-5",
    # 일하는 분야 (None = 아직 안 골랐음 → 처음 켤 때 물어봄). 분야별 단어장을 번역에 함께 알려 줌
    "fields": None,
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
                if saved.get("config_version", 1) < 7:
                    # 대화방 구분이 잘못돼 기록이 섞였던 시험 기간 기록은 모두 보관 폴더로 (지우지 않음)
                    archive_temp_histories(everything=True)
                saved["config_version"] = CONFIG_VERSION
            cfg.update(saved)
        except (OSError, ValueError):
            pass
    # 예전 버전이 아이콘을 글자로 잘못 읽어 만든 한 글자짜리 대화방 이름(예: 口)은 정리
    cfg["known_vendors"] = [v for v in cfg.get("known_vendors", []) if len(v.replace(" ", "")) >= 2]
    for e in cfg.get("title_map", []):
        if len(str(e.get("name", "")).replace(" ", "")) < 2:
            old = str(e.get("name", ""))
            e["name"] = "대화방 " + str(cfg["title_map"].index(e) + 1)
            if old:
                rename_history(old, e["name"])  # 그 이름으로 저장된 기록도 함께 옮김
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


def rename_history(old: str, new: str) -> None:
    """거래처 이름을 바꿀 때 대화 기록도 새 이름으로 옮김 (이미 있으면 합침)."""
    if old == new:
        return
    old_h = load_history(old)
    if not old_h:
        return
    save_history(new, load_history(new) + old_h)
    try:
        (data_dir() / "history" / f"{_safe_name(old)}.json").unlink()
    except OSError:
        pass


def archive_temp_histories(everything: bool = False) -> None:
    """임시 이름(대화방 N, 미지정)으로 저장된 기록을 history/_old 로 옮겨 보관 (지우지 않음)."""
    h = data_dir() / "history"
    old = h / "_old"
    for f in list(h.glob("*.json")):
        if everything or f.stem.startswith(("대화방", "_미지정")):
            old.mkdir(exist_ok=True)
            try:
                f.replace(old / f"{f.stem}_{int(f.stat().st_mtime)}.json")
            except OSError:
                pass


def history_exists(vendor: str) -> bool:
    return (data_dir() / "history" / f"{_safe_name(vendor)}.json").exists()


MEMORY_MAX = 5000


def memory_path() -> Path:
    return data_dir() / "memory.json"


def load_memory() -> dict:
    """번역 기억: 한 번 번역한 글은 다음부터 AI 없이 바로 씀 (모든 대화방 공통, 이 컴퓨터에만 저장).
    in: 업체 중국어 → 한국어, out: (말투, 대표 한국어) → 보낼 문장 후보."""
    try:
        m = json.loads(memory_path().read_text(encoding="utf-8"))
        if isinstance(m, dict):
            m.setdefault("in", {})
            m.setdefault("out", {})
            m.setdefault("tpl", {})   # 숫자만 다른 글용 문장 틀
            return m
    except (OSError, ValueError):
        pass
    # 처음에는 지금까지 쌓인 대화 기록에서 번역 기억을 채움
    mem = {"in": {}, "out": {}, "tpl": {}}
    from .chat_parser import memory_key
    for f in sorted((data_dir() / "history").glob("*.json"), key=lambda f: f.stat().st_mtime):
        try:
            for h in json.loads(f.read_text(encoding="utf-8")):
                zh, ko = h.get("zh", ""), h.get("ko", "")
                if ko and zh and h.get("src") != "panel" and re.search(r"[\u4e00-\u9fff]", zh):
                    mem["in"][memory_key(zh)] = {"ko": ko, "nuance": h.get("nuance", ""),
                                               "certainty": h.get("certainty", "none")}
        except (OSError, ValueError, AttributeError):
            continue
    return mem


_mem_pending = False
_mem_last = 0.0


def save_memory(mem: dict, force: bool = False) -> None:
    """번역 저장소 저장. 글이 많아지면 통째로 쓰는 게 무거워서, 3초 안에 또 바뀐 건 모아서 한 번에 씀
    (모아 둔 것은 UI 가 주기적으로 flush_memory 로 마저 저장하고, 끌 때도 저장)."""
    global _mem_pending
    _mem_pending = True
    if force or time.time() - _mem_last >= 3:
        flush_memory(mem)


def flush_memory(mem: dict, due_only: bool = False) -> None:
    global _mem_pending, _mem_last
    if not _mem_pending or (due_only and time.time() - _mem_last < 3):
        return
    _mem_pending, _mem_last = False, time.time()
    for k in ("in", "out", "tpl"):
        d = mem.get(k, {})
        while len(d) > MEMORY_MAX:   # 오래된 것부터 정리
            d.pop(next(iter(d)))
    try:
        memory_path().write_text(json.dumps(mem, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


LEARNED_MAX = 2000
_TERM_ZH = re.compile(r"^[\u4e00-\u9fff]{2,8}$")


def learned_path() -> Path:
    return data_dir() / "learned_terms.json"


def load_learned() -> dict:
    """쓰면서 배운 단어 {중국어: {"ko": 한국어, "n": 본 횟수}}."""
    try:
        d = json.loads(learned_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_learned(d: dict) -> None:
    while len(d) > LEARNED_MAX:   # 한 번만 본 오래된 것부터 정리
        d.pop(min(d, key=lambda k: (d[k].get("n", 0))))
    try:
        learned_path().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def learn_terms(learned: dict, text: str, terms) -> bool:
    """AI가 뽑아 준 단어 쌍을 검사해서 배운 단어에 넣음. 바뀐 게 있으면 True.
    (원문에 실제로 있는 2~8자 중국어 단어만, 숫자·긴 뜻은 거름)"""
    changed = False
    if not isinstance(terms, list):
        return False
    for t in terms[:3]:
        if not isinstance(t, dict):
            continue
        zh, ko = str(t.get("zh", "")).strip(), str(t.get("ko", "")).strip()
        if not _TERM_ZH.match(zh) or zh not in text or not (1 <= len(ko) <= 20) or re.search(r"\d", ko):
            continue
        cur = learned.get(zh)
        if cur and cur.get("ko") == ko:
            cur["n"] = cur.get("n", 1) + 1
        else:
            learned[zh] = {"ko": ko, "n": 1}
        changed = True
    return changed
