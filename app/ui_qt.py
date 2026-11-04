"""위챗 옆에 붙는 번역 패널 (Qt 화면).

위챗과 같은 색·모양으로, 위챗 창이 오른쪽으로 넓어진 것처럼 보이게 만듭니다.
번역·화면 읽기·대화방 기록 같은 동작은 예전 화면과 같습니다.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLayout,
                               QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from . import config as C
from . import shortcuts, updater, win_window
from .chat_parser import CJK_RE, is_chinese_text, memory_key, normalize, similar
from .segment import DURATION_RE, MONEY_RE, RECALL_RE, ko_time
from .prompts import TONES
from .screen_reader import ScreenReader, same_title
from .translator import TranslateError, Translator, build_request, partial_options, read_title
from .version import VERSION

FRAME = "#dcdce1"     # 위챗 바깥 회색 테두리
CARD = "#fafafa"      # 위챗 대화 배경
GREEN = "#07c160"     # 위챗 초록 (버튼)
BUBBLE_OUT = "#95ec69"  # 위챗 내 말풍선
TEXT = "#191919"
SUB = "#7a7a7a"
LINK = "#576b95"      # 위챗 링크 색
FONT = "Malgun Gothic" if sys.platform == "win32" else "WenQuanYi Zen Hei"

STYLE = f"""
QWidget#root {{ background: {FRAME}; }}
QFrame#card {{ background: {CARD}; border-radius: 10px; }}
QLabel#vendor {{ font-size: 16px; color: {TEXT}; }}
QLabel#status {{ font-size: 11px; color: #6b6b70; }}
QPushButton#flat {{ border: none; background: transparent; color: #4a4a4f; font-size: 13px; padding: 2px 6px; }}
QPushButton#flat:hover {{ color: {TEXT}; background: rgba(0,0,0,0.06); border-radius: 4px; }}
QPushButton#update {{ border: none; background: #fa9d3b; color: white; font-size: 12px; font-weight: bold;
                     border-radius: 11px; padding: 3px 10px; }}
QPushButton#tone {{ border: 1px solid #e3e3e3; background: white; color: #555; font-size: 12px;
                   border-radius: 12px; padding: 3px 12px; }}
QPushButton#tone:checked {{ background: {GREEN}; border-color: {GREEN}; color: white; }}
QPushButton#chip {{ border: 1px solid #e3e3e3; background: white; color: #444; font-size: 12px;
                   border-radius: 13px; padding: 3px 10px; }}
QPushButton#chip:hover {{ border-color: {GREEN}; color: {GREEN}; }}
QFrame#inbox {{ background: white; border: 1px solid #e5e5e5; border-radius: 8px; }}
QPlainTextEdit#input {{ border: none; background: white; font-size: 14px; color: {TEXT}; }}
QPushButton#tool {{ border: none; background: transparent; color: #4a4a4f; font-size: 12px; padding: 3px 6px; }}
QPushButton#tool:hover {{ background: rgba(0,0,0,0.06); border-radius: 4px; }}
QPushButton#tool::menu-indicator {{ width: 0px; }}
QPushButton#send {{ border: none; background: {GREEN}; color: white; font-size: 14px; border-radius: 4px;
                   padding: 6px 18px; }}
QPushButton#send:hover {{ background: #06ad56; }}
QScrollArea {{ border: none; background: transparent; }}
QWidget#log {{ background: {CARD}; }}
QToolTip {{ background: white; color: {TEXT}; border: 1px solid #e5e5e5; padding: 6px; font-size: 13px; }}
QFrame#line {{ background: #ececec; max-height: 1px; min-height: 1px; border: none; }}
QFrame#dash {{ border: none; border-top: 1px dashed #e5e5e5; max-height: 1px; min-height: 1px; }}
"""


class FlowLayout(QLayout):
    """버튼을 한 줄에 놓다가 자리가 없으면 다음 줄로 넘기는 배치."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _layout(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def needs_translation(text: str) -> bool:
    """번역할 글인지: 중국어나 영어 등 외국 글자가 있으면 번역 (숫자·기호·한국어만 있으면 그대로)."""
    import re
    if CJK_RE.search(text):
        return True
    letters = re.findall(r"[A-Za-z\u00C0-\u024F\u0400-\u04FF\u0E00-\u0E7F\u3040-\u30FF]", text)
    hangul = len(re.findall(r"[\uac00-\ud7a3]", text))
    return len(letters) >= 2 and len(letters) > hangul


class _Bridge(QObject):
    shifted = Signal(int)


class Bubble(QLabel):
    """위챗 말풍선 모양: 둥근 네모 + 프로필 사진 쪽을 가리키는 작은 꼬리."""
    TAIL = 6

    def __init__(self, parent, bg: str, fg: str, tail: str | None, tail_y: float, border: str = ""):
        super().__init__(parent)
        self._bg, self._tail, self._tail_y, self._border = QColor(bg), tail, tail_y, border
        self.setStyleSheet(f"color: {fg}; background: transparent;")

    def paintEvent(self, e):
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        T = self.TAIL
        if self._tail == "left":
            r.adjust(T, 0, 0, 0)
        elif self._tail == "right":
            r.adjust(0, 0, -T, 0)
        path = QPainterPath()
        path.addRoundedRect(r, 4, 4)
        if self._tail:
            ty = max(10.0, min(r.height() - 10.0, self._tail_y))
            if self._tail == "left":
                tri = QPolygonF([QPointF(r.left() + 1, ty - 6), QPointF(r.left() - T + 1, ty),
                                 QPointF(r.left() + 1, ty + 6)])
            else:
                tri = QPolygonF([QPointF(r.right() - 1, ty - 6), QPointF(r.right() + T - 1, ty),
                                 QPointF(r.right() - 1, ty + 6)])
            tp = QPainterPath()
            tp.addPolygon(tri)
            path = path.united(tp)
        p.fillPath(path, self._bg)
        if self._border:
            pen = QPen(QColor("#cfcfcf"))
            pen.setStyle(Qt.DashLine if self._border == "dash" else Qt.SolidLine)
            p.setPen(pen)
            p.drawPath(path)
        p.end()
        super().paintEvent(e)


class MirrorView(QWidget):
    """거울 화면: 위챗 화면의 덩어리마다 같은 높이·같은 자리에 번역 말풍선을 놓음
    (스크롤도 위챗을 그대로 따라감). 글자 크기·말풍선 꼬리·프로필 사진까지 위챗과 같게."""

    def __init__(self, on_click_entry):
        super().__init__()
        self.setObjectName("log")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._on_click = on_click_entry
        self._widgets: list = []
        self._empty = QLabel(self)
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(f"color: {SUB}; font-size: 13px;")
        self._flash = QLabel(self)
        self._flash.setWordWrap(True)
        self._flash.hide()
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._flash.hide)
        self._last = ([], "", 14)
        self._avatar_cache: dict = {}

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.show_items(*self._last)

    def flash(self, msg: str, color: str):
        self._flash.setText(msg)
        self._flash.setStyleSheet(f"background: white; color: {color}; font-size: 12px; border-radius: 6px;"
                                  "padding: 6px 10px; border: 1px solid #e5e5e5;")
        self._flash.setFixedWidth(max(120, self.width() - 24))
        self._flash.adjustSize()
        self._flash.move(12, 6)
        self._flash.raise_()
        self._flash.show()
        self._flash_timer.start(8000)

    def show_items(self, views: list, empty_text: str = "", base: int = 14):
        self._last = (views, empty_text, base)
        for w in self._widgets:
            w.deleteLater()
        self._widgets = []
        if not views:
            self._empty.setText(empty_text)
            self._empty.setGeometry(24, 0, max(10, self.width() - 48), self.height())
            self._empty.show()
            return
        self._empty.hide()
        width = self.width()
        for v in views:
            y, h = int(round(v["y"])), max(18, int(round(v["h"])))
            if y + h < 0 or y > self.height():
                continue  # 위챗 화면에서도 안 보이는 부분
            off = int(round(v.get("off") or 12))
            av = v.get("avatar")
            if av:
                self._add_avatar(av, v["side"], width)
            # (한국어 번역은 중국어보다 길어서, 반대쪽 끝 가까이까지 넓게 씀)
            maxw = max(80, width - off - 16)
            lab = self._make(v, h, maxw, base)
            if lab is None:
                continue
            if v["kind"] in ("time", "notice"):
                x = (width - lab.width()) // 2
            elif v["side"] == "out":
                x = width - off - lab.width() + (Bubble.TAIL if isinstance(lab, Bubble) else 0)
            else:
                x = off - (Bubble.TAIL if isinstance(lab, Bubble) else 0)
            lab.move(x, y + int(lab.property("dy") or 0))
            lab.show()
            self._widgets.append(lab)
        self._flash.raise_()

    def move_by(self, d: float):
        """스크롤만큼 번역 칸들을 그대로 옮김 (다시 만들지 않아서 빠르고 부드러움)."""
        self._frac = getattr(self, "_frac", 0.0) + d
        step = int(round(self._frac))
        self._frac -= step
        if not step:
            return
        for w in self._widgets:
            w.move(w.x(), w.y() + step)
        views = self._last[0]
        for v in views:
            v["y"] += step
            if v.get("avatar"):
                v["avatar"] = dict(v["avatar"], y=v["avatar"]["y"] + step)

    def _add_avatar(self, av: dict, side: str, width: int):
        from PySide6.QtGui import QPixmap
        size = max(16, int(round(av["size"])))
        key = (av["png"], size)
        pm = self._avatar_cache.get(key)
        if pm is None:
            pm = QPixmap()
            pm.loadFromData(av["png"])
            pm = pm.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            if len(self._avatar_cache) > 50:
                self._avatar_cache.clear()
            self._avatar_cache[key] = pm
        lab = QLabel(self)
        lab.setPixmap(pm)
        lab.setFixedSize(size, size)
        off = int(round(av["off"]))
        lab.move(off if side == "in" else width - off - size, int(round(av["y"])))
        lab.show()
        self._widgets.append(lab)

    def _make(self, v: dict, h: int, maxw: int, base: int):
        from PySide6.QtGui import QFontMetrics
        kind = v["kind"]
        text = v.get("text", "")
        if kind in ("photo", "video", "sticker"):
            # 사진·영상·이모티콘은 위챗 창에 그대로 보이므로 같은 크기의 빈 네모 칸에 표시만
            lab = QLabel(self)
            lab.setText(text + "\n위챗 참고")
            lab.setFont(self._font(max(11, base - 3)))
            lab.setAlignment(Qt.AlignCenter)
            lab.setFixedSize(int(min(maxw, max(60, v["w"]))), h)
            lab.setStyleSheet("background: transparent; color: #a3a3a3; border: 1px solid #e3e3e3;"
                              "border-radius: 4px;")
            return lab
        if kind in ("time", "notice"):
            lab = QLabel(self)
            lab.setText(text)
            size = max(10, base - 4)
            maxw = self.width() - 40
            # 긴 안내 문구는 위챗처럼 줄바꿈하고, 위챗 높이에 맞게 글자 크기를 줄임
            for size in range(size, 8, -1):
                r = QFontMetrics(self._font(size)).boundingRect(QRect(0, 0, maxw, 10000), Qt.TextWordWrap, text)
                if r.height() <= max(h, 20):
                    break
            lab.setFont(self._font(size))
            lab.setWordWrap(True)
            lab.setStyleSheet("color: #a3a3a3; background: transparent;")
            # 시간 줄은 위챗에서 높이가 낮아 글자가 잘릴 수 있음 → 최소 20 픽셀, 위챗 줄 가운데에 맞춤
            hh = max(h, 20)
            lab.setFixedSize(min(maxw, r.width() + 8), hh)
            lab.setAlignment(Qt.AlignCenter)
            lab.setProperty("dy", -(hh - h) // 2)
            return lab
        border = ""
        if kind == "transfer":
            bg, fg = "#fa9d3b", "white"
        elif kind == "unknown":
            bg, fg, border = "#f3f3f3", "#9a9a9a", "dash"
        else:
            c = v.get("color")
            if c:
                bg = "#%02x%02x%02x" % tuple(c[:3])
            else:
                bg = BUBBLE_OUT if v["side"] == "out" else "#ffffff"
            fg = TEXT
        if v.get("pending"):
            fg = "#9a9a9a"
            text = text or "번역 중…"
        if v.get("nuance"):
            text = text + "  💡"
        tail = "right" if v["side"] == "out" else "left"
        pad = max(8, round(base * 0.75))
        inner_w = maxw - Bubble.TAIL - 2 * pad
        # 위챗 말풍선 높이에 맞도록 글자 크기를 맞추고(위챗 글자 크기부터 3단계까지), 그래도 넘치면 …
        size = base
        for size in range(base, max(10, base - 4) - 1, -1):
            fm = QFontMetrics(self._font(size))
            r = fm.boundingRect(QRect(0, 0, inner_w, 10000), Qt.TextWordWrap, text)
            if r.height() + 8 <= h:
                break
        fm = QFontMetrics(self._font(size))
        shown = text
        while len(shown) > 1 and fm.boundingRect(QRect(0, 0, inner_w, 10000), Qt.TextWordWrap,
                                                 shown + "…").height() + 8 > h:
            shown = shown[:-2]
        if shown != text:
            shown = shown + "…"
        r = fm.boundingRect(QRect(0, 0, inner_w, 10000), Qt.TextWordWrap, shown)
        w = min(maxw, max(r.width() + 2 * pad + Bubble.TAIL + 2, 40))
        lab = Bubble(self, bg, fg, tail, v.get("tail_y") or h / 2, border)
        if v.get("entry") and self._on_click:   # 누르면 오른쪽 창에 원문·번역·속뜻을 크게
            e = v["entry"]
            lab.setCursor(Qt.PointingHandCursor)
            lab.mousePressEvent = lambda ev, e=e: self._on_click(e)
        lab.setText(shown)
        lab.setWordWrap(True)
        lab.setFont(self._font(size))
        lab.setFixedSize(int(w), h)
        lab.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lm = pad + (Bubble.TAIL if tail == "left" else 0)
        rm = pad + (Bubble.TAIL if tail == "right" else 0)
        lab.setContentsMargins(lm, 0, rm, 0)
        tip = v.get("text", "")
        if v.get("nuance"):
            tip += "\n💡 " + v["nuance"]
        if v.get("entry"):
            tip += "\n\n원문: " + v["entry"].get("zh", "")
        lab.setToolTip(tip)
        return lab

    @staticmethod
    def _font(size: int) -> QFont:
        f = QFont(FONT)
        f.setPixelSize(size)
        return f


class InputBox(QPlainTextEdit):
    """Enter = 번역, Shift+Enter = 줄바꿈. 한글 조합은 Qt 가 칸 안에서 자연스럽게 처리."""

    def __init__(self, on_enter):
        super().__init__()
        self._on_enter = on_enter

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self._on_enter()
            return
        super().keyPressEvent(e)


class Panel(QWidget):
    def __init__(self, ask_wechat_path: bool = False):
        # 항상 맨 위가 아니라 위챗 창에 딸린 창으로 붙음 (_dock_tick 에서 위챗 창을 주인으로 지정)
        super().__init__(None, Qt.FramelessWindowHint)
        self._owner = None
        self.setObjectName("root")
        self.setWindowTitle(f"바로통 v{VERSION}")
        if shortcuts.icon_path():
            self.setWindowIcon(QIcon(shortcuts.icon_path()))
        self.setStyleSheet(STYLE)
        self.setFont(QFont(FONT, 10))
        self.resize(430, 760)

        self.cfg = C.load_config()
        self.log_path = C.data_dir() / "log.txt"
        self.q: queue.Queue = queue.Queue()
        self.vendor = ""
        self.history: list[dict] = []
        self.translator = None
        self.own_clip = None
        self.last_clip = QGuiApplication.clipboard().text()
        self._last_geom = None
        self._raw_key = ""
        self._title_asked: set = set()
        self._renamed: dict = {}
        self._title_pending: set = set()
        self._last_res = None
        self._cache: dict = {}
        self._dirty = False
        self._wechat_seen = False
        self._gone_since = None
        self._hidden = False
        self._update_info = None
        self._manual_update_check = False
        self._downloading = False
        self._apply_when_ready = False
        self._pending_update = None
        self._drag = None
        self._status = "시작 중..."

        self._build()
        self.set_vendor("")

        # 스크롤 움직임은 대기 없이 바로 번역창으로 전달 (부드럽게)
        self._bridge = _Bridge()
        self._bridge.shifted.connect(self._handle_shift)
        self.reader = ScreenReader(self.cfg, lambda res: self.q.put(("scan", res)), self._own_hwnd,
                                   log_path=self.log_path, on_shift=lambda dy: self._bridge.shifted.emit(dy))
        win_window.set_main_validator(self.reader.is_main_window)
        self.reader.start()

        self._every(30, self._drain_queue)   # 스크롤을 부드럽게 따라가도록 자주 확인
        self._every(500, self._dock_tick)
        self._every(800, self._clipboard_tick)
        self._every(1000, self._status_tick)
        self._every(1000, self._lifecycle_tick)
        self._idle_since = None
        self._every(5000, self._auto_apply_tick)
        QTimer.singleShot(300, self._ensure_api_key)
        if ask_wechat_path and not self.cfg.get("wechat_path"):
            QTimer.singleShot(800, self._ask_wechat_path)
        if updater.can_update():
            QTimer.singleShot(5000, self._check_update)
            self._every(20 * 60 * 1000, self._check_update)   # 20분마다 새 버전 확인
        threading.Thread(target=shortcuts.fix_shortcut_icons, daemon=True).start()

    # ------------------------------------------------------------ 공통 도구
    def _every(self, ms, fn):
        def run():
            try:
                fn()
            except Exception:
                self._write_log(f"{fn.__name__} 오류\n{traceback.format_exc()}")
        t = QTimer(self)
        t.timeout.connect(run)
        t.start(ms)

    def _write_log(self, msg):
        try:
            with open(self.log_path, "a", encoding="utf-8") as fp:
                fp.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def _own_hwnd(self):
        try:
            return int(self.winId())
        except RuntimeError:
            return None

    def _info(self, title, text):
        QMessageBox.information(self, title, text)

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 6, 6)
        root.setSpacing(0)

        # 위쪽 회색 줄 (위챗 제목줄과 같은 높이): 상태 · 설정 · 끄기
        band = QWidget()
        band.setFixedHeight(40)
        bl = QHBoxLayout(band)
        bl.setContentsMargins(12, 0, 6, 0)
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("status")
        bl.addWidget(self.status_lbl, 1)
        gear = QPushButton("⚙ 설정")
        gear.setObjectName("flat")
        gear.clicked.connect(self._settings_menu)
        bl.addWidget(gear)
        close = QPushButton("✕")
        close.setObjectName("flat")
        close.setToolTip("번역기 끄기")
        close.clicked.connect(self.quit)
        bl.addWidget(close)
        self.band = band
        root.addWidget(band)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        root.addWidget(card, 1)

        # 거래처 이름 줄
        hd = QWidget()
        hd.setFixedHeight(58)
        hl = QHBoxLayout(hd)
        hl.setContentsMargins(18, 0, 10, 0)
        self.vendor_lbl = QLabel("")
        self.vendor_lbl.setObjectName("vendor")
        hl.addWidget(self.vendor_lbl, 1)
        self.update_btn = QPushButton("⬆ 업데이트")
        self.update_btn.setObjectName("update")
        self.update_btn.clicked.connect(self._do_update)
        self.update_btn.hide()
        hl.addWidget(self.update_btn)
        rename = QPushButton("✎ 이름")
        rename.setObjectName("flat")
        rename.setToolTip("이 대화방 이름 바꾸기")
        rename.clicked.connect(self._ask_vendor)
        hl.addWidget(rename)
        cl.addWidget(hd)
        line = QFrame()
        line.setObjectName("line")
        cl.addWidget(line)

        self.header = hd
        self.header_line = line

        # 거울 화면: 위챗 말풍선과 같은 높이에 번역 박스
        self.mirror = MirrorView(self._show_entry)
        cl.addWidget(self.mirror, 1)

        # 아래: 위챗 입력칸과 같은 모양 (입력 · 번역 결과 · 도구 줄)
        self.bottom = QWidget()
        bw = QVBoxLayout(self.bottom)
        bw.setContentsMargins(8, 6, 8, 8)
        box = QFrame()
        box.setObjectName("inbox")
        bxl = QVBoxLayout(box)
        bxl.setContentsMargins(12, 8, 12, 8)
        bxl.setSpacing(4)
        self.input = InputBox(self._send)
        self.input.setObjectName("input")
        self.input.setPlaceholderText("한국어로 쓰고 Enter (줄바꿈: Shift+Enter)")
        bxl.addWidget(self.input, 1)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.tone_btn = QPushButton()
        self.tone_btn.setObjectName("tool")
        tone_menu = QMenu(self.tone_btn)
        for key, (label, desc) in TONES.items():
            tone_menu.addAction(f"{label} — {desc[:18]}", lambda k=key: self._save_tone(k))
        self.tone_btn.setMenu(tone_menu)
        bar.addWidget(self.tone_btn)
        phrases = QPushButton("자주 쓰는 문장")
        phrases.setObjectName("tool")
        pm = QMenu(phrases)
        for phrase in self.cfg.get("quick_phrases", []):
            pm.addAction(phrase, lambda p=phrase: self._insert_phrase(p))
        phrases.setMenu(pm)
        bar.addWidget(phrases)
        self.copy_lbl = QLabel("")
        self.copy_lbl.setStyleSheet(f"font-size: 12px; color: {GREEN};")
        bar.addWidget(self.copy_lbl, 1)
        recopy = QPushButton("다시 복사")
        recopy.setObjectName("flat")
        recopy.clicked.connect(self._recopy)
        bar.addWidget(recopy)
        send = QPushButton("번역")
        send.setObjectName("send")
        send.clicked.connect(self._send)
        bar.addWidget(send)
        bxl.addLayout(bar)
        bw.addWidget(box)
        self.bottom.setFixedHeight(190)
        cl.addWidget(self.bottom)
        self._update_tone_label()
        # 보낼 문장 후보를 크게 보여 주는 작성 도우미 창 (번역 누를 때만 뜸)
        from .compose import ComposeWindow
        self.compose = ComposeWindow(self._pick_option, on_retry=self._retry_send,
                                     on_copy=self._copy, on_apply=self._apply_note)
        self._last_send = ""
        self._last_tone = "polite"
        self._last_pick = ""
        self.memory = C.load_memory()   # 한 번 번역한 글은 기억해서 AI 없이 바로 씀
        self._out_entry_id = None
        self._out_done = True
        self._user_picked = False

    # 회색 줄을 끌어서 이동 (옆에 붙기를 끈 경우)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() <= self.band.height():
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and not self.cfg.get("dock", True):
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    # ------------------------------------------------------------ 설정
    def _ensure_api_key(self):
        if not self.cfg.get("api_key"):
            self._ask_api_key(first=True)
        if self.cfg.get("api_key"):
            self.translator = Translator(self.cfg["api_key"])

    def _ask_api_key(self, first=False):
        msg = ("Claude API 키를 붙여넣어 주세요.\n(sk-ant- 로 시작합니다. 이 컴퓨터에만 저장됩니다)"
               if first else "새 Claude API 키를 붙여넣어 주세요.")
        key, ok = QInputDialog.getText(self, "API 키", msg, QLineEdit.Password)
        if ok and key.strip():
            self.cfg["api_key"] = key.strip()
            C.save_config(self.cfg)
            self.translator = Translator(self.cfg["api_key"])

    def _settings_menu(self):
        m = QMenu(self)
        m.addAction(f"업데이트 확인 (지금 v{VERSION})", self._manual_update)
        m.addSeparator()
        auto = QAction("자동 읽기", m, checkable=True, checked=self.cfg.get("auto_read", True))
        auto.toggled.connect(lambda v: self._save_toggle("auto_read", v))
        m.addAction(auto)
        fast = QAction("빠른 번역 (받은 업체 글)", m, checkable=True, checked=self.cfg.get("fast_incoming", True))
        fast.toggled.connect(lambda v: self._save_toggle("fast_incoming", v))
        m.addAction(fast)
        dock = QAction("위챗 옆에 붙기", m, checkable=True, checked=self.cfg.get("dock", True))
        dock.toggled.connect(lambda v: self._save_toggle("dock", v))
        m.addAction(dock)
        m.addSeparator()
        m.addAction("내 지시문·용어 편집", lambda: self._open(C.instructions_path()))
        m.addAction("API 키 변경", self._ask_api_key)
        m.addAction("화면 인식 확인용 사진 저장", self._save_debug)
        m.addAction("데이터 폴더 열기", lambda: self._open(C.data_dir()))
        m.addSeparator()
        m.addAction("번역기 끄기", self.quit)
        m.exec(self.mapToGlobal(QPoint(self.width() - 200, 36)))

    def _open(self, path):
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - 사용자가 직접 누른 메뉴
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _save_debug(self):
        p = C.data_dir() / "screen_check.png"
        if self.reader.save_debug_image(p):
            self._info("저장됨", f"저장했습니다:\n{p}\n\n이 사진을 비서실장에게 보내 주시면 화면 인식을 맞춰 드립니다.")
            self._open(C.data_dir())
        else:
            self._info("아직 없음", "위챗 창을 찾지 못했습니다. 위챗을 켜 두고 다시 눌러 주세요.")

    def _save_tone(self, key):
        self.cfg["tone"] = key
        C.save_config(self.cfg)
        self._update_tone_label()

    def _update_tone_label(self):
        self.tone_btn.setText("말투: " + TONES.get(self.cfg.get("tone", "polite"), TONES["polite"])[0])

    def _save_toggle(self, key, value):
        self.cfg[key] = bool(value)
        if key == "auto_read":
            self.reader.enabled = bool(value)
        C.save_config(self.cfg)

    def _ask_vendor(self):
        name, ok = QInputDialog.getText(self, "거래처 이름", "이 대화방을 패널에 어떤 이름으로 표시할까요?\n"
                                        "(바꾼 이름은 기억해 두었다가 다음에도 자동으로 씁니다)",
                                        QLineEdit.Normal, self.vendor)
        if not ok or not name.strip() or name.strip() == self.vendor:
            return
        name = name.strip()
        old = self.vendor
        if self._raw_key:
            self.cfg.setdefault("aliases", {})[self._raw_key] = name
            C.save_config(self.cfg)
        C.rename_history(old or "_미지정", name)
        self.set_vendor(name)

    def _ask_wechat_path(self):
        from . import wechat_launcher
        if wechat_launcher.find_wechat_exe(self.cfg.get("wechat_path")):
            return
        self._info("위챗 위치", "위챗 프로그램 위치를 찾지 못했습니다.\n다음 창에서 위챗 실행 파일(Weixin.exe 또는 "
                   "WeChat.exe)을 한 번만 골라 주세요. 다음부터는 자동으로 켭니다.")
        path, _ = QFileDialog.getOpenFileName(self, "위챗 실행 파일 고르기", "", "위챗 (*.exe)")
        if path:
            self.cfg["wechat_path"] = path
            C.save_config(self.cfg)
            wechat_launcher.launch(path)

    # ------------------------------------------------------------ 거래처 / 기록
    def set_vendor(self, vendor: str):
        self.vendor = vendor
        label = "이름 확인 중…" if vendor in self._title_pending else vendor
        self.vendor_lbl.setText(label or "위챗 대화방을 클릭하세요")
        # 대화방을 아직 못 읽었을 때는 예전 '미지정' 기록을 보여주지 않음
        self.history = C.load_history(vendor) if vendor else []
        for h in self.history:
            h.setdefault("id", uuid.uuid4().hex)
        self._cache = {normalize(h["zh"]): h for h in self.history if h.get("zh")}
        self._render_mirror()

    def _save(self):
        C.save_history(self.vendor or "_미지정", self.history)

    def _entry_for(self, side: str, text: str, kind: str = "text") -> dict:
        """화면의 글에 맞는 기록(번역 기억)을 찾고, 없으면 새로 만듦."""
        key = normalize(text)
        e = self._cache.get(key)
        if e is None:
            e = next((h for h in reversed(self.history[-300:]) if similar(h.get("zh", ""), text)), None)
        if e is not None and e.get("ko") and normalize(e["ko"]) == normalize(e.get("zh", "")) \
                and needs_translation(e.get("zh", "")):
            e["ko"] = ""   # 예전 버전이 영어를 번역 안 하고 그대로 저장한 기록 → 이번에 번역
        if e is None:
            e = {"id": uuid.uuid4().hex, "t": time.strftime("%Y-%m-%d %H:%M"), "side": side, "kind": kind,
                 "zh": text, "ko": ""}
            if not needs_translation(text):  # 숫자·기호·한국어만 있는 글은 그대로
                e["ko"] = text
            else:
                m = self.memory["in"].get(memory_key(text))   # 다른 대화방에서라도 전에 번역한 글이면 바로
                if m and m.get("ko"):
                    e["ko"] = m["ko"]
                    if m.get("intent"):
                        e.update(nuance=m.get("nuance", ""), certainty=m.get("certainty", "none"), intent=True)
            self.history.append(e)
            self._dirty = True
        self._cache[key] = e
        return e

    def _render_mirror(self):
        """위챗 화면에 보이는 덩어리마다 같은 높이에 박스를 그림."""
        res = self._last_res
        if res is None or not self.vendor:
            self.mirror.show_items([], "위챗 대화방을 클릭하면 여기에 번역이 나란히 나옵니다")
            return
        dpr = self.devicePixelRatioF() or 1.0
        offset = self.mirror.mapTo(self, QPoint(0, 0)).y()
        cl = res.chat_left or 0
        cr = res.chat_right or max([it.x1 for it in res.items] + [cl + 400])
        # 글자 크기: 위챗 말풍선 글자 줄 높이로 계산 (맑은 고딕이 같은 크기에서 더 커 보여서 0.76배)
        hs = sorted(it.extra["line_h"] for it in res.items if it.kind == "text" and "line_h" in it.extra)
        base = max(11, min(24, round(hs[len(hs) // 2] / dpr * 0.76))) if hs else 14
        views = []
        for it in res.items:
            v = {"kind": it.kind, "side": it.side, "y": it.y0 / dpr - offset, "h": (it.y1 - it.y0) / dpr,
                 "w": (it.x1 - it.x0) / dpr, "color": it.extra.get("bg"),
                 "off": ((it.x0 - cl) if it.side != "out" else (cr - it.x1)) / dpr}
            if "avatar_png" in it.extra and it.kind not in ("time", "notice"):
                ax0, ay0, ax1, ay1 = it.extra["avatar"]
                v["avatar"] = {"png": it.extra["avatar_png"], "size": (ax1 - ax0) / dpr, "y": ay0 / dpr - offset,
                               "off": ((ax0 - cl) if it.side != "out" else (cr - ax1)) / dpr}
                v["tail_y"] = ((ay0 + ay1) / 2 - it.y0) / dpr   # 꼬리는 프로필 사진 가운데 높이
            if it.kind == "text" and it.extra.get("cut"):
                v.update(text="⋯", pending=True)   # 화면 끝에서 잘린 글: 다 보이면 번역 (잘린 글을 번역하면 틀림)
            elif it.kind == "text":
                e = self._entry_for(it.side, it.text)
                v.update(text=e.get("ko") or ("번역 중…" if e.get("pending") else ""), entry=e,
                         nuance=e.get("nuance", ""), pending=not e.get("ko"))
            elif it.kind in ("file", "link"):
                e = self._entry_for(it.side, it.text, it.kind)
                icon = "📄 파일" if it.kind == "file" else "🔗 링크"
                v.update(text=f"{icon}: {e.get('ko') or it.text}", entry=e, pending=not e.get("ko"))
            elif it.kind == "transfer":
                amt = it.extra.get("amount")
                if not amt:
                    m = MONEY_RE.search(it.text.replace(" ", ""))
                    amt = (m.group(1) or m.group(2)).replace(",", "") if m else ""
                v["text"] = f"💰 이체 {amt}위안" if amt else "💰 이체"
            elif it.kind == "voice":
                sec = "".join(ch for ch in it.text if ch.isdigit())
                v["text"] = f"🎤 음성 {sec}초" if sec else "🎤 음성"
            elif it.kind == "video":
                m = DURATION_RE.search(it.text)
                v["text"] = f"🎬 영상 {it.extra.get('duration') or (m.group(0) if m else '')}".strip()
            elif it.kind == "sticker":
                v["text"] = "😊 이모티콘"
            elif it.kind == "photo":
                v["text"] = "📷 사진"
            elif it.kind == "time":
                v["text"] = ko_time(it.text)
            elif it.kind == "notice":
                if it.extra.get("recall") or RECALL_RE.search(it.text):
                    v["text"] = "↩ 메시지를 취소했습니다"
                elif needs_translation(it.text):
                    e = self._entry_for("center", it.text, "notice")
                    v.update(text=e.get("ko") or it.text, entry=e, pending=not e.get("ko"))
                else:
                    v["text"] = it.text
            else:
                v["text"] = "⚠ 읽지 못함 — Ctrl+C로 넣어 주세요"
            views.append(v)
        self.mirror.show_items(views, "", base)
        if getattr(self, "_title_px", 0) != base:   # 제목 글자도 위챗 제목과 같은 크기로
            self._title_px = base
            self.vendor_lbl.setStyleSheet(f"font-size: {base}px; color: {TEXT};")
        if self._dirty:
            self._dirty = False
            self._save()
        # 화면에 보이는데 아직 번역 안 된 글은 바로 번역 (글마다 한 번)
        todo = [v["entry"] for v in views if v.get("pending") and v.get("entry")
                and not v["entry"].get("pending") and not v["entry"].get("ko")]
        # 화면에 보이는 글은 한꺼번에 동시에 번역 (하나씩 차례로 하면 늦어짐). 맨 아래(최신) 글부터.
        for e in list(reversed(todo))[:20]:
            self._translate_entry(e)

    def _notice(self, msg: str, color: str):
        self.mirror.flash(msg, color)

    def _hint(self, msg: str):
        self._notice("ℹ " + msg, "#7c3aed")

    def _log_error(self, msg: str):
        self._notice("⚠ " + msg, "#dc2626")

    # ------------------------------------------------------------ 받은 메시지
    def _resolve_vendor(self, res) -> str:
        """대화방 이름 정하기: 글자로 읽은 이름 → 제목 지문으로 기억한 이름 → 새 대화방 (Claude 에게 이름을 물어봄)."""
        cfg = self.cfg
        changed = False
        registry = cfg.setdefault("title_map", [])
        best = next((e for e in registry if same_title(e["sig"], res.title_sig)), None)
        raw = res.title_text or res.vendor
        if raw:
            known = cfg.setdefault("known_vendors", [])
            canon = next((k for k in known if similar(k, raw, 0.85)), None)
            if canon is None:
                canon = raw
                known.append(raw)
                changed = True
            if best is not None and best["name"] != canon:
                C.rename_history(cfg.get("aliases", {}).get(best["name"], best["name"]), canon)
                best["name"] = canon
                changed = True
            elif best is None:
                registry.append({"sig": res.title_sig, "name": canon})
                changed = True
        elif best is not None:
            canon = best["name"]
        else:
            n = len(registry) + 1
            while C.history_exists(f"대화방 {n}") or any(e["name"] == f"대화방 {n}" for e in registry):
                n += 1
            canon = f"대화방 {n}"
            best = {"sig": res.title_sig, "name": canon}
            registry.append(best)
            changed = True
        if changed:
            cfg["title_map"] = registry[-300:]
            C.save_config(cfg)
        # 글자로 못 읽은 대화방: 제목 줄 그림을 Claude 에게 한 번 보여주고 이름을 받음
        if not raw and canon.startswith("대화방 ") and res.title_png and canon not in self._title_asked:
            self._title_asked.add(canon)
            self._title_pending.add(canon)
            self._ask_title_name(canon, res.title_png)
        self._raw_key = canon
        return cfg.get("aliases", {}).get(canon, canon)

    def _ask_title_name(self, temp_name: str, png: bytes):
        def work():
            name = ""
            if self.translator:
                try:
                    name = read_title(self.translator, self.cfg, png)
                except Exception as e:
                    self._write_log(f"Claude 이름 읽기 실패: {e}")
            if not name:  # Claude 를 못 쓰면 윈도우 글자 인식으로
                try:
                    import io

                    from PIL import Image

                    from . import korean_ocr
                    img = Image.open(io.BytesIO(png))
                    name = korean_ocr.clean_title(korean_ocr.read_text(img.resize((img.width * 2, img.height * 2))))
                    compact = name.replace(" ", "")
                    if len(compact) < 2 or sum(1 for c in compact if "\uac00" <= c <= "\ud7a3") < len(compact) * 0.5:
                        name = ""
                except Exception as e:
                    self._write_log(f"윈도우 이름 읽기 실패: {e}")
            name = name.lstrip("<‹〈 ").strip()
            self.q.put(("title_name", temp_name, name))
        threading.Thread(target=work, daemon=True).start()

    def _apply_title_name(self, temp_name: str, name: str):
        """임시 이름(대화방 N)을 Claude 가 읽은 진짜 이름으로 바꾸고 기록도 옮김."""
        self._title_pending.discard(temp_name)
        if not name:
            if self.vendor == temp_name:
                self.vendor_lbl.setText(temp_name)
            return
        changed = False
        for e in self.cfg.get("title_map", []):
            if e["name"] == temp_name:
                e["name"] = name
                changed = True
        if not changed:
            return
        known = self.cfg.setdefault("known_vendors", [])
        if name not in known:
            known.append(name)
        C.save_config(self.cfg)
        C.rename_history(temp_name, name)
        self._renamed[temp_name] = name
        self._write_log(f"대화방 이름을 Claude 로 읽음: {temp_name} → {name}")
        if self.vendor == temp_name:
            self._raw_key = name
            self.set_vendor(self.cfg.get("aliases", {}).get(name, name))

    def _match_wechat_frame(self, res):
        """위챗 맨 위 회색 줄의 높이와 색(반투명이라 바탕화면에 따라 바뀜)을 그대로 따라감."""
        dpr = self.devicePixelRatioF() or 1.0
        if res.band_h:
            h = max(24, round(res.band_h / dpr))
            if self.band.height() != h:
                self.band.setFixedHeight(h)
        if res.frame_rgb:
            color = "#%02x%02x%02x" % tuple(res.frame_rgb[:3])
            if color != getattr(self, "_frame_color", FRAME):
                self._frame_color = color
                self.setStyleSheet(STYLE.replace(f"QWidget#root {{ background: {FRAME}; }}",
                                                 f"QWidget#root {{ background: {color}; }}"))

    def _handle_scan(self, res):
        self._match_wechat_frame(res)
        if res.chat_bg:
            c = "#%02x%02x%02x" % tuple(res.chat_bg[:3])
            if c != getattr(self, "_chat_bg", ""):
                self._chat_bg = c
                self.mirror.setStyleSheet(f"QWidget#log {{ background: {c}; }}")
        vendor = self._resolve_vendor(res)
        self._last_res = res
        self._match_layout(res)
        if vendor != self.vendor:
            self.set_vendor(vendor)
        else:
            self._render_mirror()

    def _handle_shift(self, dy: int):
        """위챗을 스크롤한 만큼 번역 칸을 바로 같이 밀어 줌 (다시 그리지 않고 옮기기만 → 부드러움).
        새로 보이는 부분은 스크롤이 멈추면 읽어서 채움."""
        res = self._last_res
        if res is None:
            return
        from .screen_reader import shift_result
        self._last_res = shift_result(res, dy)
        self.mirror.move_by(dy / (self.devicePixelRatioF() or 1.0))

    def _match_layout(self, res):
        """번역창의 제목 줄·입력칸 높이를 위챗과 같게 → 말풍선 높이가 그대로 맞음."""
        dpr = self.devicePixelRatioF() or 1.0
        if res.chat_top and res.band_h:
            hh = max(36, round((res.chat_top - res.band_h) / dpr) - 1)
            if self.header.height() != hh:
                self.header.setFixedHeight(hh)
        if res.chat_bottom and res.win_h:
            bh = max(150, round((res.win_h - res.chat_bottom) / dpr) - 6)
            if self.bottom.height() != bh:
                self.bottom.setFixedHeight(bh)

    def _show_entry(self, entry: dict):
        """번역창 말풍선을 누름 → 오른쪽 측면창에 원문·번역·속뜻을 크게 (번역 전이면 번역 시작)."""
        if not entry.get("ko") and not entry.get("pending"):
            self._translate_entry(entry)
        self._shown_entry = entry.get("id")
        self._show_compose()
        state = "done" if entry.get("intent") else ("wait" if entry.get("intent_pending") else "ask")
        self.compose.show_reading(entry.get("zh", ""), entry.get("ko") or "번역 중…", entry.get("nuance", ""),
                                  intent_state=state, on_intent=lambda e=entry: self._request_intent(e))

    def _request_intent(self, entry: dict):
        """[🔍 속뜻 자세히 보기] → 그때만 AI에게 속뜻 풀이를 요청 (같은 글은 다음부터 저장소에서)."""
        m = self.memory["in"].get(memory_key(entry.get("zh", "")))
        if m and m.get("intent"):
            entry.update(nuance=m.get("nuance", ""), certainty=m.get("certainty", "none"), intent=True)
            self._dirty = True
            self._show_entry(entry)
            return
        entry["intent_pending"] = True
        self._show_entry(entry)
        self._translate_async("intent", entry["zh"], entry_id=entry["id"])

    def _translate_entry_by_id(self, entry_id):
        entry = next((h for h in self.history if h.get("id") == entry_id), None)
        if entry and not entry.get("pending"):
            self._translate_entry(entry)

    def _remember_in(self, entry):
        if entry.get("ko") and needs_translation(entry.get("zh", "")):
            self.memory["in"][memory_key(entry["zh"])] = {"ko": entry["ko"], "nuance": entry.get("nuance", ""),
                                                         "certainty": entry.get("certainty", "none"),
                                                         "intent": bool(entry.get("intent"))}
            C.save_memory(self.memory)

    def _translate_entry(self, entry):
        m = self.memory["in"].get(memory_key(entry.get("zh", "")))
        if m and m.get("ko"):   # 전에 번역한 글 → AI 없이 바로
            entry.pop("pending", None)
            entry["ko"] = m["ko"]
            if m.get("intent"):
                entry.update(nuance=m.get("nuance", ""), certainty=m.get("certainty", "none"), intent=True)
            if entry.get("src") == "clip":
                self._show_compose()
                self.compose.show_reading(entry["zh"], entry["ko"], entry.get("nuance", ""), "복사한 업체 글")
            self._dirty = True
            QTimer.singleShot(0, self._render_mirror)
            return
        if not self.translator:
            self._log_error("API 키가 없습니다. ⚙ 설정에서 API 키를 넣어 주세요.")
            return
        entry["pending"] = True
        self._translate_async("in", entry["zh"], entry_id=entry["id"])

    def _translate_async(self, direction, text, tone="polite", entry_id=None):
        if not self.translator:
            self._log_error("API 키가 없습니다. ⚙ 설정에서 API 키를 넣어 주세요.")
            return
        vendor = self.vendor
        history = [h for h in self.history if h.get("ko") and h.get("id") != entry_id]
        req = build_request(cfg=self.cfg, user_instructions=C.load_user_instructions(), vendor=vendor,
                            history=history, direction=direction, text=text, tone=tone)

        def work():
            try:
                t0 = time.perf_counter()
                if direction == "out":
                    # 보낼 문장 후보는 AI가 쓰는 대로 완성된 것부터 바로 보여 줌
                    seen = [0]

                    def on_text(acc):
                        opts = partial_options(acc)
                        if len(opts) > seen[0]:
                            seen[0] = len(opts)
                            self.q.put(("partial_out", text, opts))
                            if len(opts) == 1:
                                self._write_log(f"첫 후보 {time.perf_counter() - t0:.1f}초")
                    try:
                        data = self.translator.run(req, on_text=on_text)
                    except TranslateError:
                        raise
                    except Exception:   # 흘려 받기가 안 되는 환경이면 한 번에 받기
                        data = self.translator.run(req)
                else:
                    try:
                        data = self.translator.run(req)
                    except TranslateError as e:
                        if req.get("model") != self.cfg.get("fast_model", "claude-haiku-5-5"):
                            raise
                        # 빠른 AI 가 안 되면 기본 AI 로 한 번 더 (번역이 빠지지 않게)
                        self._write_log(f"빠른 번역 실패 → 기본 AI 로: {e}")
                        req2 = build_request(cfg=dict(self.cfg, fast_incoming=False),
                                             user_instructions=C.load_user_instructions(), vendor=vendor,
                                             history=history, direction=direction, text=text, tone=tone)
                        data = self.translator.run(req2)
                self._write_log(f"번역 {direction} {time.perf_counter() - t0:.1f}초 ({len(text)}자, "
                                f"{req.get('model')})")
                self.q.put(("done", direction, vendor, entry_id, text, data))
            except TranslateError as e:
                self.q.put(("error", str(e), vendor, entry_id))
            except Exception as e:
                self.q.put(("error", f"알 수 없는 오류: {e}", vendor, entry_id))

        self._status = "번역 중..."
        threading.Thread(target=work, daemon=True).start()

    def _history_of(self, vendor):
        vendor = self._renamed.get(vendor, vendor)  # 번역 중에 대화방 이름이 바뀐 경우 (대화방 N → 진짜 이름)
        return self.history if vendor == self.vendor else C.load_history(vendor or "_미지정")

    def _store(self, vendor, hist):
        vendor = self._renamed.get(vendor, vendor)
        if vendor == self.vendor:
            self.history = hist
            self._save()
            self._render_mirror()
        else:
            C.save_history(vendor or "_미지정", hist)

    def _handle_done(self, direction, vendor, entry_id, text, data):
        hist = self._history_of(vendor)
        if direction in ("in", "intent"):
            entry = next((h for h in hist if h.get("id") == entry_id), None)
            if entry is None:
                return
            entry.pop("pending", None)
            entry.pop("intent_pending", None)
            if direction == "intent":   # 대표가 눌러서 요청한 속뜻 풀이
                entry.update(nuance=data.get("nuance", ""), certainty=data.get("certainty", "none"), intent=True)
                if not entry.get("ko"):
                    entry["ko"] = data.get("korean", "")
            else:
                entry["ko"] = data.get("korean", "")
            self._remember_in(entry)
            if self.compose.isVisible() and getattr(self, "_shown_entry", None) == entry_id:
                self._show_entry(entry)
            if entry.get("src") == "clip":  # 복사해서 번역한 글: 작성 도우미 창에 크게 보여줌
                self._show_compose()
                self.compose.show_reading(entry["zh"], entry["ko"], entry.get("nuance", ""), "복사한 업체 글")
                self.copy_lbl.setText("복사한 글을 번역했습니다")
        else:
            options = [o for o in data.get("options", []) if o.get("chinese")]
            if not options and data.get("chinese"):
                options = [{"label": "추천", "chinese": data["chinese"],
                            "back_translation": data.get("back_translation", "")}]
            if not options:
                self.compose.show_error("번역 결과가 비어 있습니다. 다시 만들기를 눌러 주세요.")
                return
            first = options[0]
            entry = {"id": uuid.uuid4().hex, "t": time.strftime("%Y-%m-%d %H:%M"), "side": "out",
                     "src": "panel", "ko": text, "zh": first["chinese"], "back": first.get("back_translation", ""),
                     "note": data.get("note", ""), "options": options}
            hist.append(entry)
            self._out_entry_id = entry["id"]
            if not data.get("_from_memory"):
                self.memory["out"][self._last_tone + "|" + text.strip()] = {
                    "options": options, "note": data.get("note", "")}
                C.save_memory(self.memory)
            self._show_compose()
            shown = text.split(self.APPLY_TAG)[0] + ("  (+ 제안 반영)" if self.APPLY_TAG in text else "")
            self._out_done = True
            self.compose.show_options(shown, options, data.get("note", ""))
            if getattr(self, "_user_picked", False) and self._last_pick:
                # 후보가 다 나오기 전에 대표가 이미 고른 문장은 그대로 둠
                self.compose.mark_text(self._last_pick)
                entry["zh"] = self._last_pick
            else:
                # 추천 문장은 바로 복사해 둠 (다른 후보를 누르면 그걸로 바뀜)
                self.compose.mark_first()
                if self._last_pick != first["chinese"]:
                    self._copy(first["chinese"])
                self._last_pick = first["chinese"]
        self._store(vendor, hist)

    def _handle_error(self, msg, vendor, entry_id):
        self._log_error(msg)
        if not entry_id and self.compose.isVisible():
            self.compose.show_error(msg)
        if entry_id:
            hist = self._history_of(vendor)
            for h in hist:
                if h.get("id") == entry_id:
                    h.pop("pending", None)
                    h.pop("intent_pending", None)
            self._store(vendor, hist)

    # ------------------------------------------------------------ 보내는 메시지
    def _send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.copy_lbl.setText("")
        self._last_send = text
        self._out_done = False
        self._user_picked = False
        tone = self.cfg.get("tone", "polite")
        self._last_tone = tone
        self._show_compose()
        m = self.memory["out"].get(tone + "|" + text)
        if m and m.get("options"):   # 전에 똑같이 쓴 말 → AI 없이 바로 (다시 만들기를 누르면 새로)
            self._handle_done("out", self.vendor, None, text, dict(m, _from_memory=True))
            return
        past = self._similar_sent(text)
        if past:   # 전에 비슷하게 보낸 말 → 먼저 보여 주고, 원하면 그때 AI로 새로
            past_mine, pm = past
            self._out_entry_id = None
            self.compose.show_similar(text, past_mine, pm["options"],
                                      lambda: (self.compose.show_waiting(text),
                                               self._translate_async("out", text, tone=tone)))
            return
        self.compose.show_waiting(text)
        self._translate_async("out", text, tone=tone)

    def _similar_sent(self, text: str):
        """번역 저장소에서 비슷한 한국어 문장 찾기 (85% 이상 비슷하고 숫자가 똑같을 때만)."""
        import re
        from difflib import SequenceMatcher
        digits = re.findall(r"\d+", text)
        key = memory_key(text)
        best, best_r = None, 0.85
        for k, v in self.memory["out"].items():
            mine = k.split("|", 1)[1] if "|" in k else k
            if self.APPLY_TAG in mine or re.findall(r"\d+", mine) != digits or not v.get("options"):
                continue
            r = SequenceMatcher(None, key, memory_key(mine)).ratio()
            if r >= best_r:
                best, best_r = (mine, v), r
        return best

    def _handle_partial_out(self, text: str, options: list):
        """후보가 하나씩 완성될 때마다 바로 보여 주고, 첫 후보(추천)는 바로 복사."""
        if text != self._last_send or self._out_done:
            return
        shown = text.split(self.APPLY_TAG)[0] + ("  (+ 제안 반영)" if self.APPLY_TAG in text else "")
        self.compose.show_options(shown, options, "")
        if not self._user_picked:
            self.compose.mark_first()
            if self._last_pick != options[0]["chinese"]:
                self._last_pick = options[0]["chinese"]
                self._copy(options[0]["chinese"])
        else:
            self.compose.mark_text(self._last_pick)

    def _retry_send(self):
        if self._last_send:
            self._out_done = False
            self._user_picked = False
            self.compose.show_waiting(self._last_send)
            self._translate_async("out", self._last_send, tone=self.cfg.get("tone", "polite"))

    APPLY_TAG = "\n\n[함께 반영할 제안] "

    def _apply_note(self, note: str):
        """참고 메모의 제안을 넣어서 후보를 다시 만듦 (AI 1번 사용, 같은 제안이면 다음엔 기억에서)."""
        base = self._last_send.split(self.APPLY_TAG)[0]
        if not base:
            return
        text = base + self.APPLY_TAG + note
        self._last_send = text
        self._out_done = False
        self._user_picked = False
        tone = self.cfg.get("tone", "polite")
        self._last_tone = tone
        m = self.memory["out"].get(tone + "|" + text)
        if m and m.get("options"):
            self._handle_done("out", self.vendor, None, text, dict(m, _from_memory=True))
            return
        self.compose.show_waiting(base + "  (+ 제안 반영)")
        self._translate_async("out", text, tone=tone)

    def _pick_option(self, chinese: str, opt: dict):
        """작성 도우미 창에서 후보를 고름 → 복사, 기록도 실제로 보낼 문장으로 바꿈."""
        self._last_pick = chinese
        self._user_picked = True
        self._copy(chinese)
        e = next((h for h in self.history if h.get("id") == self._out_entry_id), None)
        if e is None and self._last_send:   # 저장소에서 고른 문장도 대화 기록에 남김
            e = {"id": uuid.uuid4().hex, "t": time.strftime("%Y-%m-%d %H:%M"), "side": "out", "src": "panel",
                 "ko": self._last_send.split(self.APPLY_TAG)[0], "zh": "", "back": "", "note": ""}
            self.history.append(e)
            self._out_entry_id = e["id"]
        if e is not None:
            e["zh"], e["back"] = chinese, opt.get("back_translation", "")
            self._save()
            self._render_mirror()

    def _show_compose(self):
        """작성 도우미 창을 번역창 오른쪽에 같은 높이로 붙임 (자리가 없으면 번역창 위에 겹쳐서)."""
        g = self.frameGeometry()
        scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        cw = 400
        x = g.right() + 1 if g.right() + cw <= scr.right() else g.left()
        self.compose.setGeometry(x, g.top(), cw, g.height())
        self.compose.show()
        self.compose.raise_()
        try:
            hwnd = int(self.compose.winId())
            if self._owner:
                win_window.set_owner(hwnd, self._owner)
            win_window.style_like_wechat(hwnd)
        except Exception:
            pass

    def _insert_phrase(self, phrase):
        self.input.insertPlainText(phrase)
        self.input.setFocus()

    def _copy(self, text):
        QGuiApplication.clipboard().setText(text)
        self.own_clip = text
        self.last_clip = text
        self.copy_lbl.setText("✓ 복사됨 · 위챗 입력창에 Ctrl+V")

    def _recopy(self):
        if self._last_pick:
            self._copy(self._last_pick)

    # ------------------------------------------------------------ 자동 업데이트
    def _check_update(self, manual: bool = False):
        def work():
            try:
                info = updater.check_latest()
            except Exception as e:
                self._write_log(f"업데이트 확인 실패: {e}")
                if manual:
                    self.q.put(("update_msg", f"업데이트 확인에 실패했습니다.\n\n{e}"))
                return
            if info:
                self.q.put(("update", info))
            elif manual:
                self.q.put(("update_msg", f"지금 쓰시는 v{VERSION}이 최신 버전입니다."))
        threading.Thread(target=work, daemon=True).start()

    def _manual_update(self):
        if not updater.can_update():
            self._info("업데이트 확인", "설치된 실행 파일에서만 업데이트할 수 있습니다.")
            return
        self._manual_update_check = True
        self._check_update(manual=True)

    def _show_update(self, info):
        """새 버전 발견 → 뒤에서 몰래 받아 둠. 다 받으면 위챗을 끌 때(또는 버튼을 누르면 바로) 적용."""
        self._update_info = info
        pending = updater.pending_update()
        if pending and pending[1] >= info["version"]:
            self._update_ready(pending[0], pending[1])
            return
        if not self._downloading:
            self._start_download(info, apply_now=False)

    def _start_download(self, info, apply_now: bool):
        self._downloading = True
        self._apply_when_ready = apply_now
        self._dl_version = info["version"]
        # 뒤에서 받는 중에도 보이게 (안 보이면 업데이트가 안 되는 것처럼 보임)
        self.update_btn.setText(f"⬇ v{info['version']} 받는 중")
        self.update_btn.setEnabled(False)
        self.update_btn.show()

        def work():
            try:
                path = updater.download(info["url"], version=info["version"], kind=info.get("kind", "exe"),
                                        progress=lambda p: self.q.put(("update_progress", p)))
                self.q.put(("update_ready", path, info["version"]))
            except Exception as e:
                self.q.put(("update_failed", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _update_ready(self, path, version):
        self._pending_update = path
        self.update_btn.setText(f"⬆ v{version} 지금 적용")
        self.update_btn.setEnabled(True)
        self.update_btn.show()
        self._write_log(f"새 버전 v{version} 받아 둠 → 쓰는 중이 아닐 때 자동 적용")

    def _auto_apply_tick(self):
        """받아 둔 새 버전을 알아서 적용: 입력칸이 비어 있고 작성 도우미 창이 닫혀 있고 번역 중이 아닐 때.
        번역기만 10초쯤 꺼졌다 켜지고 위챗은 그대로."""
        if not self._pending_update or self._hidden:
            return
        busy = (self.input.toPlainText().strip() or self.compose.isVisible()
                or self._status.startswith("번역") or any(h.get("pending") for h in self.history[-30:]))
        if busy:
            self._idle_since = None
            return
        if self._idle_since is None:
            self._idle_since = time.time()
        elif time.time() - self._idle_since >= 20:   # 20초 동안 아무것도 안 할 때
            self._write_log("새 버전 자동 적용")
            self._do_update()

    def _do_update(self):
        """업데이트 버튼: 받아 둔 게 있으면 바로 적용(다시 켜짐), 없으면 받은 뒤 바로 적용."""
        if self._pending_update:
            self._save()
            updater.apply_and_restart(self._pending_update, restart=True)
            self._pending_update = None
            self.quit()
            return
        self._apply_when_ready = True
        if not self._downloading and self._update_info:
            self._start_download(self._update_info, apply_now=True)
        self.update_btn.setEnabled(False)
        self.update_btn.show()

    # ------------------------------------------------------------ 반복 작업
    def _drain_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "scan":
                    self._handle_scan(item[1])
                elif kind == "shift":
                    self._handle_shift(item[1])
                elif kind == "partial_out":
                    self._handle_partial_out(item[1], item[2])
                elif kind == "done":
                    self._handle_done(*item[1:])
                    self._status = ""
                elif kind == "error":
                    self._handle_error(*item[1:])
                    self._status = ""
                elif kind == "title_name":
                    self._apply_title_name(item[1], item[2])
                elif kind == "update":
                    self._show_update(item[1])
                    if self._manual_update_check:
                        self._manual_update_check = False
                        self._do_update()
                elif kind == "update_msg":
                    self._manual_update_check = False
                    self._info("업데이트 확인", item[1])
                elif kind == "update_progress":
                    v = getattr(self, "_dl_version", "")
                    self.update_btn.setText(f"⬇ v{v} 받는 중 {item[1]}%")
                elif kind == "update_ready":
                    self._downloading = False
                    self._update_ready(item[1], item[2])
                    if self._apply_when_ready:
                        self._do_update()
                        return
                elif kind == "update_failed":
                    self._downloading = False
                    self._write_log(f"업데이트 받기 실패: {item[1]}")
                    self.update_btn.setText("⬆ 업데이트")
                    self.update_btn.setEnabled(True)
                    if self._apply_when_ready:
                        self._log_error(f"업데이트 실패: {item[1]} 잠시 후 다시 시도해 주세요.")
                        self.update_btn.setText("⬆ 업데이트")
                        self.update_btn.setEnabled(True)
        except queue.Empty:
            pass

    def _dock_tick(self):
        if not self.cfg.get("dock", True) or self._hidden:
            return
        found = win_window.find_wechat()
        if not found:
            return
        hwnd, (l, t, r, b) = found
        own = self._own_hwnd()
        if own and hwnd != self._owner:
            win_window.set_owner(own, hwnd)
            win_window.style_like_wechat(own)
            self._owner = hwnd
            self._write_log(f"위챗 창에 붙임 owner={hwnd}")
        screen = QGuiApplication.primaryScreen()
        scale = screen.devicePixelRatio() if screen else 1.0
        w = int(max(self.cfg.get("panel_width", 400), 430) * scale)
        sw, _ = win_window.screen_size()
        if r + w <= sw:
            x = r
        elif l - w >= 0:
            x = l - w
        else:
            x = 0
        geom = (x, t, w, b - t)
        if geom != self._last_geom:
            if sys.platform == "win32" and own:
                win_window.place_visible(own, *geom)  # 위챗과 위아래 끝·높이를 정확히 맞춤 (화면 픽셀 기준)
            else:
                self.setGeometry(int(x / scale), int(t / scale), int(w / scale), int((b - t) / scale))
            self._last_geom = geom
            self._write_log(f"dock wechat={(l, t, r, b)} screen={sw} panel={geom}")

    def _clipboard_tick(self):
        if not self.cfg.get("clipboard_watch", True):
            return
        clip = QGuiApplication.clipboard().text()
        if not clip or clip == self.last_clip:
            return
        self.last_clip = clip
        found = win_window.find_wechat()
        fg = win_window.foreground_hwnd()
        from_wechat = sys.platform != "win32" or (found and fg in (found[0], self._own_hwnd()))
        if from_wechat and clip != self.own_clip and is_chinese_text(clip):
            clip = clip.strip()
            entry = next((h for h in reversed(self.history) if similar(h["zh"], clip)), None)
            if entry is None:
                entry = {"id": uuid.uuid4().hex, "t": time.strftime("%Y-%m-%d %H:%M"),
                         "side": "in", "zh": clip, "ko": "", "src": "clip"}
                self.history.append(entry)
                self._cache[normalize(clip)] = entry
                self._save()
            if not entry.get("ko") and not entry.get("pending"):
                self._translate_entry(entry)

    def _status_tick(self):
        text = self._status if self._status.startswith("번역") else self.reader.status
        self.status_lbl.setText(text)

    def _lifecycle_tick(self):
        """위챗 최소화 → 패널 숨김, 위챗 닫힘(트레이 포함) 5초 → 번역기 완전히 종료."""
        state = win_window.wechat_state()
        if state == "visible":
            self._wechat_seen = True
            self._gone_since = None
            if self._hidden:
                self.show()
                self._hidden = False
                self._last_geom = None
        elif state == "minimized":
            self._gone_since = None
            if self.cfg.get("dock", True) and not self._hidden:
                self.hide()
                self.compose.hide()
                self._hidden = True
        elif self._wechat_seen and sys.platform == "win32":
            if self._gone_since is None:
                self._gone_since = time.time()
            elif time.time() - self._gone_since > 5:
                self._write_log("위챗이 닫혀서 번역기도 종료")
                self.quit()

    def quit(self):
        try:
            self.compose.hide()
            # 받아 둔 새 버전이 있으면 꺼지는 김에 바꿔 끼움 → 다음에 켤 때 바로 새 버전
            if self._pending_update:
                updater.apply_and_restart(self._pending_update, restart=False)
                self._pending_update = None
            self.reader.stop()
        finally:
            QApplication.instance().quit()


def run(ask_wechat_path: bool = False):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    p = Panel(ask_wechat_path=ask_wechat_path)
    p.show()
    return app.exec()
