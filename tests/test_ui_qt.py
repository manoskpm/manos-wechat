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
    cfg["fields"] = []   # 분야 선택 창이 시험을 막지 않게
    C.save_config(cfg)
    p = ui.Panel()

    class FakeTr:
        def run(self, req):
            txt = req["messages"][0]["content"].split("<message>\n")[1].split("\n</message>")[0]
            if "outgoing" in req["messages"][0]["content"]:
                return {"options": [{"label": "정중하게(추천)", "chinese": "中:" + txt, "back_translation": "역:" + txt},
                                    {"label": "짧게", "chinese": "短:" + txt, "back_translation": "짧:" + txt}],
                        "note": ""}
            if "작업: intent" in req["messages"][0]["content"]:
                return {"korean": "한:" + txt, "nuance": "속:" + txt, "certainty": "high"}
            return {"korean": "한:" + txt}

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
    assert p.history[-1]["zh"] == "中:샘플 보내주세요" and "복사됨" in p.copy_lbl.text()   # 추천 문장은 바로 복사
    assert p.compose.isVisible()                                   # 작성 도우미 창에 후보가 뜸
    from PySide6.QtGui import QGuiApplication
    from app.compose import _Option
    opts = [w for w in p.compose._widgets if isinstance(w, _Option)]
    assert len(opts) == 2
    opts[1].clicked.emit(opts[1])                                  # 다른 후보를 고르면 그걸로 복사·기록
    assert QGuiApplication.clipboard().text() == "短:샘플 보내주세요" and p.history[-1]["zh"] == "短:샘플 보내주세요"


def test_mirror_every_item_gets_a_box(panel):
    """위챗 덩어리 수 = 번역 박스 수, 같은 순서·같은 간격 (빈 줄 0개)."""
    p = panel
    p.resize(400, 1100)          # 실제로는 위챗 창 높이에 맞춰짐
    p.show()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    mixed = [("time", "center", "Thursday 11:08"), ("text", "in", "单号：123 这个发了吗"),
             ("photo", "in", ""), ("sticker", "in", ""), ("text", "out", "300"),
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
    assert texts[4] == "300"                                   # 숫자만 있는 글은 그대로
    assert "이체 170.00위안" in texts[7] and "음성 5초" in texts[8] and "영상 0:35" in texts[9]
    assert "취소" in texts[10] and "읽지 못함" in texts[11]


def test_memory_reuses_translations_without_api(panel):
    """한 번 번역한 글은 다른 대화방에서도, 문장부호가 조금 달라도 AI 없이 바로 (쓸수록 빨라지는 번역기)."""
    p = panel
    calls = []
    run = p.translator.run
    p.translator.run = lambda req: (calls.append(req), run(req))[1]
    _scan(p, "工厂甲", [3] * 1920, [("in", "好的，知道了")])
    _scan(p, "工厂甲", [3] * 1920, [("in", "好的，知道了")])
    assert len(calls) == 1 and p.history[-1]["ko"] == "한:好的，知道了"
    _scan(p, "工厂乙", [200] * 1920, [("in", "好的,知道了")])        # 다른 방, 쉼표 모양이 다름
    assert len(calls) == 1 and p.history[-1]["ko"] == "한:好的，知道了"
    p.input.setPlainText("샘플 보내주세요")
    p._send()
    p._drain_queue()
    p.input.setPlainText("샘플 보내주세요")
    p._send()                                                    # 똑같이 쓴 말 → 후보도 기억에서 바로
    p._drain_queue()
    assert len(calls) == 2 and p.history[-1]["zh"] == "中:샘플 보내주세요"


def test_similar_sentence_from_store_and_note_apply(panel):
    """비슷한 말은 저장소에서 먼저(무료), 숫자가 다르면 새로. 참고 메모 반영 버튼은 AI로 다시."""
    p = panel
    calls = []
    run = p.translator.run
    p.translator.run = lambda req: (calls.append(req), run(req))[1]
    _scan(p, "工厂丙", [9] * 1920, [("in", "你好")])
    p.input.setPlainText("사장님 샘플 300개 보내주세요")
    p._send(); p._drain_queue()
    assert len(calls) == 2                                   # 你好 번역 1 + 보낼 문장 1
    p.input.setPlainText("사장님, 샘플 300개 보내 주세요!")    # 거의 같은 말 → 저장소에서
    p._send(); p._drain_queue()
    assert len(calls) == 2
    from app.compose import _Option
    opts = [w for w in p.compose._widgets if isinstance(w, _Option)]
    opts[0].clicked.emit(opts[0])
    assert p.history[-1]["zh"] == "中:사장님 샘플 300개 보내주세요" and p.history[-1]["ko"] == "사장님, 샘플 300개 보내 주세요!"
    p.input.setPlainText("사장님 샘플 500개 보내주세요")        # 숫자가 다르면 저장소 안 씀
    p._send(); p._drain_queue()
    assert len(calls) == 3
    p._apply_note("날짜도 물어보세요 '什么时候发货'")
    p._drain_queue()
    assert len(calls) == 4 and "[함께 반영할 제안]" in calls[-1]["messages"][0]["content"]


def test_scroll_moves_boxes_immediately(panel):
    """위챗을 스크롤하면 글자 인식을 기다리지 않고 번역 칸이 같은 만큼 바로 움직임."""
    p = panel
    p.resize(400, 1100); p.show()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    _scan(p, "工厂丁", [5] * 1920, [("in", "你好"), ("in", "明天发货")])
    _scan(p, "工厂丁", [5] * 1920, [("in", "你好"), ("in", "明天发货")])
    before = sorted(w.y() for w in p.mirror._widgets)
    p._handle_shift(100)
    after = sorted(w.y() for w in p.mirror._widgets)
    assert [b + 100 for b in before] == after


def test_english_is_translated(panel):
    """영어로 쓴 글(대표가 직접 쓴 것 포함)도 번역. 숫자·한국어만 있는 글은 그대로."""
    p = panel
    _scan(p, "工厂戊", [11] * 1920, [("out", "How much is the unit price?"), ("in", "2026"), ("out", "감사합니다")])
    _scan(p, "工厂戊", [11] * 1920, [("out", "How much is the unit price?"), ("in", "2026"), ("out", "감사합니다")])
    kos = {h["zh"]: h["ko"] for h in p.history}
    assert kos["How much is the unit price?"] == "한:How much is the unit price?"
    assert kos["2026"] == "2026" and kos["감사합니다"] == "감사합니다"


def test_click_bubble_shows_detail(panel):
    """번역창 말풍선을 누르면 오른쪽 창에 원문·번역이 크게."""
    p = panel
    p.resize(400, 1100); p.show()
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.processEvents()
    _scan(p, "工厂己", [13] * 1920, [("in", "有点难度")])
    _scan(p, "工厂己", [13] * 1920, [("in", "有点难度")])
    bubble = next(w for w in p.mirror._widgets if "有点难度" in w.text())
    bubble.mousePressEvent(None)
    assert p.compose.isVisible()
    texts = [w.text() for w in p.compose._widgets if isinstance(w, QLabel)]
    assert "有点难度" in texts and "한:有点难度" in texts


def test_intent_only_when_asked(panel):
    """속뜻은 평소엔 안 하고, 말풍선을 누른 뒤 [속뜻 자세히 보기]를 누를 때만 AI로 (같은 글은 다음부터 저장소에서)."""
    p = panel
    calls = []
    run = p.translator.run
    p.translator.run = lambda req: (calls.append(req["messages"][0]["content"]), run(req))[1]
    _scan(p, "工厂庚", [17] * 1920, [("in", "有点难度")])
    _scan(p, "工厂庚", [17] * 1920, [("in", "有点难度")])
    e = p.history[-1]
    assert e["ko"] == "한:有点难度" and not e.get("nuance") and len(calls) == 1
    p._show_entry(e)
    p._request_intent(e)
    p._drain_queue()
    assert e["nuance"] == "속:有点难度" and "작업: intent" in calls[-1] and len(calls) == 2
    _scan(p, "工厂辛", [201] * 1920, [("in", "有点难度")])          # 다른 방에서 같은 글
    e2 = p.history[-1]
    assert e2["ko"] == "한:有点难度" and e2.get("nuance") == "속:有点难度" and len(calls) == 2


def test_first_candidate_shows_before_all_done(panel):
    """보낼 문장: 첫 후보가 완성되면 다른 후보를 기다리지 않고 바로 보여 주고 복사."""
    import json
    p = panel
    from PySide6.QtGui import QGuiApplication
    from app.compose import _Option
    seen = []

    class StreamTr:
        def run(self, req, on_text=None):
            data = {"options": [{"label": "정중하게(추천)", "chinese": "中:첫", "back_translation": "역:첫"},
                                {"label": "짧게", "chinese": "中:둘", "back_translation": "역:둘"}], "note": ""}
            full = json.dumps(data, ensure_ascii=False)
            if on_text:
                cut = full.index("}, ") + 1
                on_text(full[:cut])
                p._drain_queue()      # 이 순간 화면 확인
                seen.append(([w.opt["chinese"] for w in p.compose._widgets if isinstance(w, _Option)],
                             QGuiApplication.clipboard().text()))
                on_text(full)
            return data
    p.translator = StreamTr()
    p.input.setPlainText("샘플 보내 주세요")
    p._send()
    p._drain_queue()
    assert seen == [(["中:첫"], "中:첫")]                        # 첫 후보만 먼저, 이미 복사됨
    assert [w.opt["chinese"] for w in p.compose._widgets if isinstance(w, _Option)] == ["中:첫", "中:둘"]
