"""문장 틀 저장: 숫자만 다른 글은 AI 없이 재사용.

예) "库存有500个" → 한국어 "재고가 500개 있습니다" 를 "재고가 ⟦0⟧개 있습니다" 틀로 저장.
    다음에 "库存有300个" 가 오면 틀에 300 을 끼워서 바로 보여 줌.

안전 원칙 (숫자 실수 방지):
- 한국어 번역에 나온 숫자가 모두 중국어 원문에 있던 숫자와 글자 그대로 같을 때만 틀로 저장.
  (단위 환산·쉼표 표기 1,000 처럼 숫자가 달라진 번역은 저장하지 않음)
- 숫자가 서로 같은 자리(500个500元)인지 다른 자리(500个300元)인지까지 같아야 같은 틀로 봄.
"""
from __future__ import annotations

import re

from .chat_parser import memory_key

NUM_RE = re.compile(r"\d+(?:\.\d+)?")
MARK = "⟦{}⟧"


def _skeleton(zh: str):
    """숫자를 순서 번호로 바꾼 글과, 나온 순서대로의 서로 다른 숫자 목록."""
    values: list[str] = []

    def sub(m):
        v = m.group(0)
        if v not in values:
            values.append(v)
        return "#%d" % values.index(v)

    return NUM_RE.sub(sub, zh), values


def make_template(zh: str, ko: str):
    """(열쇠, 한국어 틀) 또는 None."""
    if not zh or not ko or "⟦" in ko:
        return None
    skel, values = _skeleton(zh)
    if not values:
        return None
    if len(re.sub(r"#\d+", "", memory_key(skel))) < 2:   # 숫자 말고 글자가 거의 없으면 틀로 쓰지 않음
        return None
    ko_nums = NUM_RE.findall(ko)
    if not ko_nums or any(n not in values for n in ko_nums) or any(v not in ko_nums for v in values):
        return None

    def sub(m):
        return MARK.format(values.index(m.group(0)))

    return memory_key(skel), NUM_RE.sub(sub, ko)


def apply_template(zh: str, tpl_map: dict):
    """저장된 틀로 번역을 만듦. 없으면 None."""
    skel, values = _skeleton(zh)
    if not values:
        return None
    tpl = tpl_map.get(memory_key(skel))
    if not tpl:
        return None
    out = tpl
    for i, v in enumerate(values):
        out = out.replace(MARK.format(i), v)
    return None if "⟦" in out else out
