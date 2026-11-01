from pathlib import Path

import pytest

from app.chat_parser import Line, find_new_incoming, is_chinese_text, parse_chat, similar


def L(x0, y0, x1, y1, t):
    return Line(x0, y0, x1, y1, t)


def test_groups_wrapped_lines_and_sides():
    lines = [
        L(150, 20, 260, 40, "老王"),
        L(20, 80, 340, 96, "老板您好，这款手办最低起订量是500个，单价28元，交"),
        L(20, 100, 95, 116, "期大概25天。"),
        L(220, 140, 480, 158, "您好，我们想先从300个开始合作"),
        L(225, 180, 275, 196, "14:20"),
        L(20, 220, 330, 236, "300个的话单价要32元。"),
        L(20, 700, 300, 716, "입력창 글자는 무시"),
    ]
    vendor, bubbles = parse_chat(lines, 500, 760, title_height=64, input_height=190)
    assert vendor == "老王"
    assert [(b.side, b.text) for b in bubbles] == [
        ("in", "老板您好，这款手办最低起订量是500个，单价28元，交期大概25天。"),
        ("out", "您好，我们想先从300个开始合作"),
        ("in", "300个的话单价要32元。"),
    ]


def test_group_member_count_removed_from_title():
    vendor, _ = parse_chat([L(100, 20, 300, 40, "工厂群(12)")], 500, 760, 64, 190)
    assert vendor == "工厂群"


def test_find_new_incoming_skips_known_and_limits():
    from app.chat_parser import Bubble
    bubbles = [Bubble("in", f"消息{i}号", i, i) for i in range(6)] + [Bubble("out", "我的消息", 9, 9)]
    new = find_new_incoming(bubbles, ["消息0号", "消息 1号"], max_new=3)
    assert new == ["消息3号", "消息4号", "消息5号"]


def test_similar_tolerates_ocr_noise():
    assert similar("300个的话单价要32元，样品可以", "300个的话单价要32元,样品可以")
    assert not similar("单价28元", "交期25天")


def test_is_chinese_text():
    assert is_chinese_text("单价多少？")
    assert not is_chinese_text("단가 얼마예요")
    assert not is_chinese_text("hello")


def test_real_wechat_screenshot():
    """대표님 PC의 실제 위챗 화면 캡처로 확인 (한국어 이름은 못 읽고, 사진 속 작은 글씨는 무시)."""
    pytest.importorskip("rapidocr_onnxruntime")
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    from app.config import DEFAULTS
    from app.screen_reader import analyze_window

    path = Path(__file__).parent / "fixtures" / "real_wechat.png"
    if not path.exists():  # 실제 대화가 담긴 사진이라 저장소에는 올리지 않음
        pytest.skip("real_wechat.png 없음")
    img = Image.open(path)
    result, _ = RapidOCR()(np.array(img))
    res = analyze_window(img, result, dict(DEFAULTS))
    assert 360 <= res.chat_left <= 390  # 대화방 목록과 대화 영역의 경계 (약 375px)
    assert [(b.side, b.text) for b in res.bubbles if b.side == "in"] == [("in", "物流公司让今天送货")]
    assert all(b.side == "out" for b in res.bubbles if "样品" in b.text)


def test_merge_rows_joins_split_line():
    from app.chat_parser import merge_rows
    merged = merge_rows([L(476, 98, 742, 115, "麻烦告诉"), L(746, 98, 797, 116, "一下,谢")])
    assert len(merged) == 1 and merged[0].text == "麻烦告诉一下,谢"


def test_detect_chat_left_from_list_dates():
    from app.chat_parser import detect_chat_left
    lines = [L(314, 199, 361, 216, "10/30"), L(323, 281, 363, 300, "10/28"),
             L(582, 182, 695, 201, "Thursday 03:30")]
    assert detect_chat_left(lines, 905) == 371


def test_real_wechat_screenshot2():
    """실제 화면 2: 사진 속 글자 무시, 짧은 메시지(2件, 好的)와 2줄 말풍선 인식."""
    pytest.importorskip("rapidocr_onnxruntime")
    path = Path(__file__).parent / "fixtures" / "real_wechat2.png"
    if not path.exists():
        pytest.skip("real_wechat2.png 없음")
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    from app.config import DEFAULTS
    from app.screen_reader import analyze_window

    img = Image.open(path)
    result, _ = RapidOCR()(np.array(img))
    res = analyze_window(img, result, dict(DEFAULTS))
    ins = [b.text for b in res.bubbles if b.side == "in"]
    assert ins == ["2件", "上衣架：19公斤裤架：24公斤", "好的"]
    assert len([b for b in res.bubbles if b.side == "out"]) == 2


def _b(side, text):
    from app.chat_parser import Bubble
    return Bubble(side, text, 0, 0)


def test_merge_new_chat_translates_only_latest():
    from app.chat_parser import merge_into_history
    hist, auto = merge_into_history([], [_b("in", "你好"), _b("out", "单价多少"), _b("in", "单价28元")])
    assert [h["zh"] for h in hist] == ["你好", "单价多少", "单价28元"]
    assert [a["zh"] for a in auto] == ["单价28元"]


def test_merge_new_messages_below_anchor_are_translated():
    from app.chat_parser import merge_into_history
    old = [{"side": "in", "zh": "你好", "ko": "안녕하세요"}, {"side": "out", "zh": "单价多少", "ko": "단가?"}]
    hist, auto = merge_into_history(old, [_b("in", "你好"), _b("out", "单价多少"),
                                          _b("in", "好的"), _b("in", "明天发货")])
    assert [h["zh"] for h in hist] == ["你好", "单价多少", "好的", "明天发货"]
    assert [a["zh"] for a in auto] == ["好的", "明天发货"]


def test_merge_scrolled_up_old_messages_not_translated():
    from app.chat_parser import merge_into_history
    old = [{"side": "in", "zh": "明天发货", "ko": "내일 발송"}]
    # 위로 스크롤: 처음 보는 옛날 메시지들 + 기준점
    hist, auto = merge_into_history(old, [_b("in", "样品寄出了"), _b("out", "谢谢"), _b("in", "明天发货")])
    assert [h["zh"] for h in hist] == ["样品寄出了", "谢谢", "明天发货"]
    assert auto == []
    # 기준점이 하나도 안 보일 만큼 더 올라감
    hist2, auto2 = merge_into_history(hist, [_b("in", "你好老板")])
    assert hist2[0]["zh"] == "你好老板" and auto2 == []


def test_merge_duplicate_short_message_and_card():
    from app.chat_parser import merge_into_history
    old = [{"side": "in", "zh": "好的", "ko": "네"}, {"side": "out", "zh": "发货了吗", "ko": ""}]
    hist, auto = merge_into_history(old, [_b("in", "好的"), _b("out", "发货了吗"), _b("in", "好的"),
                                          _b("in", "妖野向MANOS分享销售单单号:A8012")])
    assert [h["zh"] for h in hist] == ["好的", "发货了吗", "好的"]
    assert [a["zh"] for a in auto] == ["好的"]
