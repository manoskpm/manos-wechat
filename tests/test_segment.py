"""거울 화면용 덩어리 나누기: 위챗 모양 그림을 직접 그려서 확인 (실제 대화 캡처는 저장소에 올리지 않음)."""
import random

from PIL import Image, ImageDraw

from app.chat_parser import Line
from app.segment import ko_time, segment_chat

BG = (250, 250, 250)


def _chat():
    img = Image.new("RGB", (700, 900), BG)
    d = ImageDraw.Draw(img)
    lines = []

    def avatar(side, y):
        x = 20 if side == "in" else 620
        d.rectangle([x, y, x + 44, y + 44], fill=(200, 30, 30) if side == "in" else (190, 190, 190))

    def bubble(side, y, w, h, text, color):
        avatar(side, y)
        x = 76 if side == "in" else 608 - w
        d.rounded_rectangle([x, y, x + w, y + h], 4, fill=color)
        lines.append(Line(x + 12, y + 12, x + w - 12, y + h - 12, text))

    bubble("in", 40, 140, 44, "空白包装发货", (236, 236, 240))
    bubble("out", 110, 300, 68, "老板以后我们订的所有货", (156, 240, 156))
    d.text((300, 200), "Tuesday 11:59", fill=(160, 160, 160))
    lines.append(Line(300, 200, 380, 212, "Tuesday 11:59"))
    avatar("in", 240)                                    # 사진: 알록달록한 큰 칸
    rnd = random.Random(1)
    for yy in range(240, 440, 10):
        for xx in range(76, 276, 10):
            d.rectangle([xx, yy, xx + 9, yy + 9], fill=tuple(rnd.randrange(256) for _ in range(3)))
    bubble("in", 470, 260, 100, "报价单.xlsx 1.2M", (236, 236, 240))
    lines[-1] = Line(88, 482, 300, 558, "报价单.xlsx 1.2M")
    bubble("in", 600, 60, 44, "可以", (236, 236, 240))
    avatar("in", 680)                                    # 아래 끝에서 잘린 사진
    for yy in range(680, 780, 10):
        for xx in range(76, 196, 10):
            d.rectangle([xx, yy, xx + 9, yy + 9], fill=tuple(rnd.randrange(256) for _ in range(3)))
    return img, lines


def test_segment_mixed_chat():
    img, lines = _chat()
    items = segment_chat(img, lines, 0, 700, 0, 762, BG)
    got = [(i.kind, i.side) for i in items]
    assert got == [("text", "in"), ("text", "out"), ("time", "center"), ("photo", "in"),
                   ("file", "in"), ("text", "in"), ("photo", "in")]
    assert items[0].text == "空白包装发货" and items[0].y0 == 40
    assert items[1].extra["bg"][1] > 200                 # 내 말풍선 초록색 그대로


def test_ko_time():
    assert ko_time("Thursday 11:08") == "목요일 11:08"
    assert ko_time("昨天 09:12") == "어제 09:12"


EXPECTED = {
    "gabang": "photo/in text/in text/out text/in text/in time/center text/out text/in time/center photo/in",
    "real2": "photo/in text/in time/center text/out text/in text/out text/in",
    "nahee": "time/center photo/in file/in",
    "hui": "photo/out photo/in photo/in",
    "narrow": "text/in photo/out",
    "u33": "text/in photo/out text/in text/out text/out text/in text/out link/in notice/in",
    "u34": "text/in text/in photo/in photo/in photo/in",
}


def test_real_screens_all_display_scales():
    """실제 위챗 화면(저장소에 올리지 않는 개인 자료)을 배율 100·125·150·200% 로 바꿔도 같은 결과."""
    import os
    import pytest
    from PIL import Image
    here = os.path.join(os.path.dirname(__file__), "fixtures")
    files = {n: os.path.join(here, f"real_{n}.png") for n in EXPECTED}
    files = {n: f for n, f in files.items() if os.path.exists(f)}
    if not files:
        pytest.skip("개인 화면 자료 없음")
    try:
        from app.config import DEFAULTS
        from app.screen_reader import ScreenReader
        r = ScreenReader(dict(DEFAULTS), None, lambda: None)
        r._get_ocr()
    except Exception as e:
        pytest.skip(f"글자 인식 사용 불가: {e}")
    for name, f in files.items():
        base = Image.open(f).convert("RGB")
        scales = (1.0, 1.25, 1.5, 2.0) if not name.startswith("u") else (1.0,)
        for s in scales:
            img = base if s == 1.0 else base.resize((round(base.width * s), round(base.height * s)), Image.NEAREST)
            r._chat_left = None
            got = " ".join(f"{i.kind}/{i.side}" for i in r.scan_image(img).items)
            assert got == EXPECTED[name], f"{name} x{s}"


def test_partial_read_after_scroll_matches_full_read():
    """스크롤하면 새로 보인 줄만 읽어서 합친 결과 = 화면 전체를 다시 읽은 결과."""
    import os
    import numpy as np
    import pytest
    from PIL import Image
    f = os.path.join(os.path.dirname(__file__), "fixtures", "real_gabang.png")
    if not os.path.exists(f):
        pytest.skip("개인 화면 자료 없음")
    from app.config import DEFAULTS
    from app.screen_reader import ScreenReader, new_region, shift_result
    r = ScreenReader(dict(DEFAULTS), None, lambda: None)
    base = Image.open(f).convert("RGB")
    first = r.scan_image(base)
    top, bottom = first.chat_top + 1, first.chat_bottom - 1
    clean = np.asarray(base).copy()
    clean[top:top + 30] = (250, 250, 250)        # 맨 위에 잘려 보이던 조각은 지움
    after = Image.fromarray(clean)                 # 스크롤한 뒤 화면 (아래에 새 대화가 보임)
    dy = 160
    before = clean.copy()                          # 스크롤 전: 내용이 dy 만큼 아래에 있었음
    before[top + dy:bottom] = clean[top:bottom - dy]
    before[top:top + dy] = (250, 250, 250)
    prev = shift_result(r.scan_image(Image.fromarray(before)), -dy)
    roi = new_region(prev, -dy)
    assert roi is not None
    part = r.scan_image(after, roi=roi, prev=prev)
    full = r.scan_image(after)
    sig = lambda res: [(i.kind, i.side, i.y0 // 4) for i in res.items]
    assert part.timing["part"] and sig(part) == sig(full)


def test_one_char_bubble_is_not_avatar():
    """'好' 같은 한 글자 말풍선(정사각형)도 프로필 사진으로 착각하지 않음."""
    img = Image.new("RGB", (500, 300), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 100, 64, 144], fill=(200, 30, 30))          # 프로필 사진
    d.rounded_rectangle([76, 100, 118, 142], 4, fill=(236, 236, 240))   # 好 (거의 정사각형)
    items = segment_chat(img, [Line(88, 110, 106, 132, "好")], 0, 500, 0, 300, BG)
    assert [(i.kind, i.side, i.text) for i in items] == [("text", "in", "好")]
