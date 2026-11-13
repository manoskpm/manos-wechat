"""번역 점검과 도움말: 숫자 대조 경고, 위안→원 환산, 비슷한 과거 번역 찾기.

모두 AI를 쓰지 않는 계산이다 (프로그램이 직접 확인).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .chat_parser import memory_key

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
ZH_NUMERAL = re.compile(r"[一二三四五六七八九十百千万两零半]")


def _nums(text: str) -> list[str]:
    """글 속 숫자 (쉼표 표기는 같은 숫자로: 1,200 → 1200)."""
    out = []
    for t in NUM_RE.findall(text):
        t = t.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t) else t
        out.append(t)
    return out


def number_check(src: str, dst: str, check_extra: bool = True) -> dict:
    """원문과 번역의 숫자를 대조. 없어진 숫자(missing), 번역에만 있는 숫자(extra)를 돌려줌.
    - 원문에 있는 숫자가 번역에 글자 그대로 없으면 missing
    - 번역에만 있는 숫자는 원문에 중국어 숫자(三百 등)가 없을 때만 extra (한자 숫자를 풀어 쓴 것은 정상)"""
    s, d = _nums(src), _nums(dst)
    missing = sorted({n for n in s if n not in d}, key=s.index)
    extra = []
    if check_extra and not ZH_NUMERAL.search(src):
        extra = sorted({n for n in d if n not in s}, key=d.index)
    return {"missing": missing, "extra": extra}


def number_warning(src: str, dst: str, check_extra: bool = True) -> str:
    """사람이 읽는 경고 글. 문제 없으면 빈 글."""
    r = number_check(src, dst, check_extra)
    parts = []
    if r["missing"]:
        parts.append("원문의 숫자 " + ", ".join(r["missing"]) + " 이(가) 번역에 없어요")
    if r["extra"]:
        parts.append("번역에만 있는 숫자 " + ", ".join(r["extra"]))
    return ("⚠ 숫자를 확인해 주세요: " + " / ".join(parts)) if parts else ""


# ---- 위안 → 원 환산
YUAN_ZH = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:元|块钱|块|RMB|rmb|CNY|cny|人民币)|[¥￥]\s*(\d[\d,]*(?:\.\d+)?)")
YUAN_KO = re.compile(r"(\d[\d,]*(?:\.\d+)?)(\s*)(위안|RMB|rmb|CNY|cny)")


def format_won(n: float) -> str:
    if n >= 100_000_000:
        v = f"{n / 100_000_000:.1f}".rstrip("0").rstrip(".")
        return f"약 {v}억원"
    if n >= 10_000:
        v = f"{n / 10_000:.1f}".rstrip("0").rstrip(".")
        return f"약 {v}만원"
    return f"약 {int(round(n, -1)):,}원"


def _val(s: str) -> float:
    return float(s.replace(",", ""))


def yuan_amounts(zh: str) -> list[float]:
    """중국어 원문에서 위안 금액 (元·块·RMB·¥ 가 붙은 숫자)."""
    out = []
    for m in YUAN_ZH.finditer(zh):
        try:
            out.append(_val(m.group(1) or m.group(2)))
        except ValueError:
            pass
    return out


def annotate_yuan(ko: str, rate) -> str:
    """번역문의 '1200위안' 뒤에 '(약 22.8만원)'을 붙임. 환율이 없으면 그대로 (화면에만 쓰고 저장은 안 함)."""
    if not rate:
        return ko

    def sub(m):
        try:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}({format_won(_val(m.group(1)) * rate)})"
        except ValueError:
            return m.group(0)

    return YUAN_KO.sub(sub, ko)


def won_lines(zh: str, rate) -> str:
    """측면창에 보일 환산 안내. 위안 금액이 없으면 빈 글."""
    amts = yuan_amounts(zh)
    if not amts:
        return ""
    if not rate:
        return "💴 위안 금액이 있어요. ⚙ 설정 → 환율 설정에서 환율을 넣으면 원화로 보여 드려요."
    seen, lines = set(), []
    for a in amts:
        if a in seen:
            continue
        seen.add(a)
        lines.append(f"{a:g}위안 ≈ {format_won(a * rate)}")
    return "💴 " + " · ".join(lines) + f"  (1위안 = {rate:g}원 기준)"


# ---- 비슷한 과거 번역 찾기
def _best(items, key: str, k: int, min_ratio: float):
    """items: (비교글, 보여줄 짝, 고친 번역 여부) → 가장 비슷한 k개."""
    if len(key) < 4:
        return []
    found = []
    n = len(key)
    for cand, pair, fixed in items:
        m = len(cand)
        if cand == key or m < n * 0.5 or m > n * 2:
            continue
        sm = SequenceMatcher(None, key, cand, autojunk=False)
        if sm.real_quick_ratio() < min_ratio or sm.quick_ratio() < min_ratio:
            continue
        r = sm.ratio()
        if r >= min_ratio:
            found.append((r + (0.1 if fixed else 0), cand, pair))
    found.sort(key=lambda t: -t[0])
    return [(c, p) for _, c, p in found[:k]]


def similar_examples(memory: dict, text: str, direction: str, k: int = 3, min_ratio: float = 0.55,
                     scan_max: int = 3000):
    """번역할 글과 비슷한 과거 번역 (원문, 번역) 최대 k개. 사용자가 고친 번역을 우선.
    in/intent: 업체 중국어 → 한국어, out: 대표 한국어 → 보낸 중국어."""
    key = memory_key(text)
    if direction == "out":
        items = []
        for k2, v in list(memory.get("out", {}).items())[-scan_max:]:
            src = k2.split("|", 1)[-1]
            opts = v.get("options") or []
            if opts and opts[0].get("chinese"):
                items.append((memory_key(src), (src, opts[0]["chinese"]), False))
        res = _best(items, key, k, min_ratio)
        return [(pair[0], pair[1]) for _, pair in res]
    items = [(k2, (k2, v.get("ko", "")), bool(v.get("fixed")))
             for k2, v in list(memory.get("in", {}).items())[-scan_max:] if v.get("ko")]
    return [(c, p[1]) for c, p in _best(items, key, k, min_ratio)]
