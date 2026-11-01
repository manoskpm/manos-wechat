"""새 Qt 패널을 화면 없이 띄워 대화방 전환·자동 번역·이름 읽기·보내기를 확인."""
import types

import pytest


@pytest.fixture()
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as e:  # 화면 부품이 없는 환경
        pytest.skip(f"PySide6 사용 불가: {e}")
    from unittest.mock import MagicMock
    app = QApplication.instance() or QApplication([])
    import app.ui_qt as ui
    from app import config as C
    monkeypatch.setattr(ui, "ScreenReader", MagicMock())
    monkeypatch.setattr(ui, "read_title", lambda tr, cfg, png: "칭펑 핸드메이드")
    monkeypatch.setattr(ui.threading, "Thread", lambda target, daemon: types.SimpleNamespace(start=target))
    cfg = C.load_config()
    cfg["api_key"] = "x"
    C.save_config(cfg)
    p = ui.Panel()

    class FakeTr:
        def run(self, req):
            txt = req["messages"][0]["content"].split("<message>\n")[1].split("\n</message>")[0]
            if "outgoing" in req["messages"][0]["content"]:
                return {"chinese": "中:" + txt, "back_translation": "역:" + txt, "note": ""}
            return {"korean": "한:" + txt, "nuance": "", "certainty": "none"}

    p.translator = FakeTr()
    yield p
    p.close()
    app.processEvents()


def _scan(p, title, sig, bubbles, png=b""):
    """bubbles: [(side, text)] 또는 [(kind, side, text)] → 위에서부터 차례로 놓인 덩어리."""
    from app.screen_reader import ScanResult
    from app.segment import Item
    items, y = [], 120
    for b in bubbles:
        kind, side, text = b if len(b) == 3 else ("text", *b)
        items.append(Item(kind, side, y, y + 40, 400, 600, text))
        y += 60
    p._handle_scan(ScanResult("", sig, [], 300, 90, title, png, band_h=30, items=items,
                              chat_top=90, chat_bottom=900, win_h=1100))
    p._drain_queue()


def _boxes(p):
    """번역창에 실제로 그려진 박스 (글자, 위쪽 위치)."""
    return [(w.text(), w.y()) for w in p.mirror._widgets]


def test_panel_flow(panel):
    p = panel
    sig_a, sig_b = [0] * 1920, [255] * 960 + [0] * 960
    _scan(p, "", sig_a, [("in", "样品明天寄出"), ("in", "物流公司让今天送货")], png=b"png")
    assert p.vendor == "칭펑 핸드메이드"                      # 이름 못 읽는 방 → Claude 로 이름 읽기
    _scan(p, "", sig_a, [("in", "样品明天寄出"), ("in", "物流公司让今天送货")])
    assert [h.get("ko") for h in p.history] == ["한:样品明天寄出", "한:物流公司让今天送货"]  # 보이는 메시지 바로 번역
    _scan(p, "A汇星盛通中韩双向", sig_b, [("in", "好的")])
    assert p.vendor == "A汇星盛通中韩双向" and len(p.history) == 1  # 다른 방과 섞이지 않음
    _scan(p, "", sig_a, [("in", "物流公司让今天送货"), ("in", "明天到")])
    assert p.vendor == "칭펑 핸드메이드" and p.history[-1]["ko"] == "한:明天到"  # 새 메시지 자동 번역
    p.history[0]["ko"] = ""
    p._translate_entry_by_id(p.history[0]["id"])
    p._drain_queue()
    assert p.history[0]["ko"] == "한:样品明天寄出"            # 눌러서 번역 (화면에 안 보이는 옛날 메시지)
    p.input.setPlainText("샘플 보내주세요")
    p._send()
    p._drain_queue()
    assert p.history[-1]["zh"] == "中:샘플 보내주세요" and "복사됨" in p.copy_lbl.text()


def test_mirror_every_item_gets_a_box(panel):
    """위챗 덩어리 수 = 번역 박스 수, 같은 순서·같은 간격 (빈 줄 0개)."""
    p = panel
    p.resize(400, 1100)          # 실제로는 위챗 창 높이에 맞춰짐
    p.show()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    mixed = [("time", "center", "Thursday 11:08"), ("text", "in", "单号：123 这个发了吗"),
             ("photo", "in", ""), ("sticker", "in", ""), ("text", "out", "yes"),
             ("file", "in", "报价单.xlsx 1.2M"), ("link", "in", "[Link] 新品"),
             ("transfer", "out", "¥170.00"), ("voice", "in", "5\""), ("video", "in", "0:35"),
             ("notice", "center", "对方撤回了一条消息"), ("unknown", "in", "")]
    _scan(p, "测试工厂", [7] * 1920, mixed)
    _scan(p, "测试工厂", [7] * 1920, mixed)
    boxes = _boxes(p)
    assert len(boxes) == len(mixed)
    ys = [y for _, y in boxes]
    assert ys == sorted(ys) and len({b - a for a, b in zip(ys, ys[1:])}) == 1   # 위챗과 같은 간격
    texts = [t for t, _ in boxes]
    assert texts[0] == "목요일 11:08"
    assert texts[1].startswith("한:单号")                      # 单号 들어간 글도 빠지지 않음
    assert texts[4] == "yes"                                   # 중국어 없는 글은 그대로
    assert "이체 170.00위안" in texts[7] and "음성 5초" in texts[8] and "영상 0:35" in texts[9]
    assert "취소" in texts[10] and "읽지 못함" in texts[11]
