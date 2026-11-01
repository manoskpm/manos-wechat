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
    from app.chat_parser import Bubble
    from app.screen_reader import ScanResult
    p._handle_scan(ScanResult("", sig, [Bubble(s, t, 0, 0) for s, t in bubbles], 300, 90, title, png))
    p._drain_queue()


def test_panel_flow(panel):
    p = panel
    sig_a, sig_b = [0] * 1920, [255] * 960 + [0] * 960
    _scan(p, "", sig_a, [("in", "样品明天寄出"), ("in", "物流公司让今天送货")], png=b"png")
    assert p.vendor == "칭펑 핸드메이드"                      # 이름 못 읽는 방 → Claude 로 이름 읽기
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
