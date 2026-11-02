"""작성 도우미 창: 대표가 쓴 한국어를 업체에 보낼 중국어 '후보 2~3개'로 크게 보여 주고, 누르면 복사.

번역창 오른쪽에 붙어서 뜨며, 문장을 고르면 자동으로 닫힙니다.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

FONT = "Malgun Gothic" if sys.platform == "win32" else "WenQuanYi Zen Hei"
GREEN = "#07c160"
TEXT = "#191919"

STYLE = f"""
QWidget#compose {{ background: #dcdce1; font-family: '{FONT}'; }}
QFrame#ccard {{ background: #fafafa; border-radius: 10px; }}
QLabel#ctitle {{ font-size: 15px; color: {TEXT}; }}
QLabel#mine {{ font-size: 13px; color: #6b6b70; }}
QFrame#opt {{ background: white; border: 1px solid #e6e6e6; border-radius: 8px; }}
QFrame#opt:hover {{ border-color: {GREEN}; }}
QFrame#opt[picked="true"] {{ border: 2px solid {GREEN}; background: #f3fbf6; }}
QLabel#chip {{ font-size: 12px; color: white; background: {GREEN}; border-radius: 9px; padding: 1px 8px; }}
QLabel#chipalt {{ font-size: 12px; color: #4a4a4f; background: #ececec; border-radius: 9px; padding: 1px 8px; }}
QLabel#zh {{ font-size: 17px; color: {TEXT}; }}
QLabel#ko {{ font-size: 13px; color: #7a7a7a; }}
QLabel#copied {{ font-size: 12px; color: {GREEN}; }}
QLabel#note {{ font-size: 13px; color: #b36b00; }}
QFrame#notebox {{ background: #fff8ec; border-radius: 8px; }}
QPushButton#flat {{ border: none; background: transparent; color: #4a4a4f; font-size: 13px; padding: 2px 6px; }}
QPushButton#flat:hover {{ background: rgba(0,0,0,0.06); border-radius: 4px; }}
"""


class _Option(QFrame):
    clicked = Signal(object)

    def __init__(self, opt: dict, best: bool):
        super().__init__()
        self.setObjectName("opt")
        self.setCursor(Qt.PointingHandCursor)
        self.opt = opt
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        chip = QLabel(opt.get("label", ""))
        chip.setObjectName("chip" if best else "chipalt")
        top.addWidget(chip)
        top.addStretch(1)
        self.copied = QLabel("")
        self.copied.setObjectName("copied")
        top.addWidget(self.copied)
        v.addLayout(top)
        zh = QLabel(opt.get("chinese", ""))
        zh.setObjectName("zh")
        zh.setWordWrap(True)
        zh.setTextInteractionFlags(Qt.NoTextInteraction)
        v.addWidget(zh)
        ko = QLabel("↩ " + opt.get("back_translation", ""))
        ko.setObjectName("ko")
        ko.setWordWrap(True)
        v.addWidget(ko)

    def mousePressEvent(self, e):
        self.clicked.emit(self)

    def set_picked(self, on: bool):
        self.setProperty("picked", "true" if on else "false")
        self.copied.setText("✓ 복사됨 · 위챗 입력창에 Ctrl+V" if on else "")
        self.style().unpolish(self)
        self.style().polish(self)


class ComposeWindow(QWidget):
    """보낼 문장 고르기 창. on_pick(chinese, option) 은 후보를 눌렀을 때 호출."""

    def __init__(self, on_pick, on_retry=None, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Tool)
        self.setObjectName("compose")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self._on_pick, self._on_retry = on_pick, on_retry
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.hide)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 8, 8)
        root.setSpacing(0)
        band = QWidget()
        band.setFixedHeight(40)
        bl = QHBoxLayout(band)
        bl.setContentsMargins(14, 0, 6, 0)
        t = QLabel("보낼 문장 고르기")
        t.setStyleSheet("font-size: 12px; color: #6b6b70;")
        bl.addWidget(t)
        bl.addStretch(1)
        x = QPushButton("✕")
        x.setObjectName("flat")
        x.clicked.connect(self.hide)
        bl.addWidget(x)
        root.addWidget(band)
        card = QFrame()
        card.setObjectName("ccard")
        self.body = QVBoxLayout(card)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)
        root.addWidget(card, 1)
        self._widgets: list = []

    def _clear(self):
        for w in self._widgets:
            w.deleteLater()
        self._widgets = []
        while self.body.count():
            self.body.takeAt(0)

    def show_waiting(self, mine: str):
        self._clear()
        self._add(self._label("내가 쓴 말", "mine"))
        self._add(self._label(mine, "ctitle", wrap=True))
        self._add(self._label("문장 후보를 만드는 중…", "mine"))
        self.body.addStretch(1)

    def show_options(self, mine: str, options: list, note: str = ""):
        self._clear()
        self._add(self._label("내가 쓴 말", "mine"))
        self._add(self._label(mine, "ctitle", wrap=True))
        for i, opt in enumerate(options):
            w = _Option(opt, best=(i == 0))
            w.clicked.connect(self._picked)
            self._add(w)
        if note:
            box = QFrame()
            box.setObjectName("notebox")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 8, 12, 8)
            bl.addWidget(self._label("※ " + note, "note", wrap=True))
            self._add(box)
        self.body.addStretch(1)
        if self._on_retry:
            row = QHBoxLayout()
            row.addStretch(1)
            again = QPushButton("다시 만들기")
            again.setObjectName("flat")
            again.clicked.connect(self._on_retry)
            row.addWidget(again)
            holder = QWidget()
            holder.setLayout(row)
            self._add(holder)

    def show_error(self, msg: str):
        self._clear()
        self._add(self._label(msg, "note", wrap=True))
        self.body.addStretch(1)

    def _picked(self, w: _Option):
        for o in self._widgets:
            if isinstance(o, _Option):
                o.set_picked(o is w)
        self._on_pick(w.opt.get("chinese", ""), w.opt)
        self._close_timer.start(1500)   # 고르면 잠깐 '복사됨'을 보여 주고 닫힘

    def _add(self, w):
        self.body.addWidget(w)
        self._widgets.append(w)

    @staticmethod
    def _label(text: str, name: str, wrap: bool = False) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName(name)
        lab.setWordWrap(wrap)
        return lab
