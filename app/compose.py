"""작성 도우미 창: 대표가 쓴 한국어를 업체에 보낼 중국어 '후보 2~3개'로 크게 보여 주고, 누르면 복사.

번역창 오른쪽에 붙어서 뜨며, 문장을 고르면 자동으로 닫힙니다.
"""
from __future__ import annotations

import html
import re
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

FONT = "Malgun Gothic" if sys.platform == "win32" else "WenQuanYi Zen Hei"
GREEN = "#07c160"
TEXT = "#191919"

STYLE = f"""
QWidget#compose {{ background: #dcdce1; font-family: '{FONT}'; }}
QFrame#ccard {{ background: #fafafa; border-radius: 10px; }}
QLabel#ctitle {{ font-size: 16px; color: {TEXT}; }}
QLabel#mine {{ font-size: 13px; color: #6b6b70; }}
QFrame#opt {{ background: white; border: 1px solid #e6e6e6; border-radius: 8px; }}
QFrame#opt:hover {{ border-color: {GREEN}; }}
QFrame#opt[picked="true"] {{ border: 2px solid {GREEN}; background: #f3fbf6; }}
QLabel#chip {{ font-size: 13px; color: white; background: {GREEN}; border-radius: 9px; padding: 1px 8px; }}
QLabel#chipalt {{ font-size: 13px; color: #4a4a4f; background: #ececec; border-radius: 9px; padding: 1px 8px; }}
QLabel#zh {{ font-size: 20px; color: {TEXT}; }}
QLabel#ko {{ font-size: 14px; color: #7a7a7a; }}
QLabel#copied {{ font-size: 13px; color: {GREEN}; }}
QLabel#note {{ font-size: 14px; color: #b36b00; }}
QFrame#notebox {{ background: #fff8ec; border-radius: 8px; }}
QPushButton#apply {{ border: 1px solid #f0c27a; background: white; color: #b36b00; font-size: 13px;
                    border-radius: 12px; padding: 4px 12px; }}
QPushButton#apply:hover {{ background: #fff1d6; }}
QPushButton#flat {{ border: none; background: transparent; color: #4a4a4f; font-size: 13px; padding: 2px 6px; }}
QPushButton#flat:hover {{ background: rgba(0,0,0,0.06); border-radius: 4px; }}
"""


CJK_RUN = re.compile(r"[0-9A-Za-z]*[\u4e00-\u9fff][\u4e00-\u9fff0-9A-Za-z，。？！、～~]*")


def note_html(note: str) -> str:
    """메모 속 중국어 부분에 밑줄 → 누르면 그 부분만 복사."""
    from urllib.parse import quote
    out, last = [], 0
    for m in CJK_RUN.finditer(note):
        zh = m.group(0).strip()
        out.append(html.escape(note[last:m.start()]))
        out.append(f'<a href="copy:{quote(zh)}" style="color:#576b95;">{html.escape(m.group(0))}</a>')
        last = m.end()
    out.append(html.escape(note[last:]))
    return "※ " + "".join(out)


class _Option(QFrame):
    clicked = Signal(object)

    def __init__(self, opt: dict, best: bool):
        super().__init__()
        self.setObjectName("opt")
        self.setCursor(Qt.PointingHandCursor)
        self.opt = opt
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
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

    def __init__(self, on_pick, on_retry=None, on_copy=None, on_apply=None, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Tool)
        self.setObjectName("compose")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self._on_pick, self._on_retry = on_pick, on_retry
        self._on_copy, self._on_apply = on_copy, on_apply
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
        self.body.setSpacing(14)
        root.addWidget(card, 1)
        self._widgets: list = []

    def _clear(self):
        for w in self._widgets:
            w.deleteLater()
        self._widgets = []
        while self.body.count():
            self.body.takeAt(0)

    def show_waiting(self, mine: str):
        self._close_timer.stop()
        self._clear()
        self._add(self._label("내가 쓴 말", "mine"))
        self._add(self._label(mine, "ctitle", wrap=True))
        self._add(self._label("문장 후보를 만드는 중…", "mine"))
        self.body.addStretch(1)

    def show_options(self, mine: str, options: list, note: str = ""):
        self._close_timer.stop()
        self._clear()
        self._add(self._label("내가 쓴 말", "mine"))
        self._add(self._label(mine, "ctitle", wrap=True))
        for i, opt in enumerate(options):
            w = _Option(opt, best=(i == 0))
            w.clicked.connect(self._picked)
            self._add(w)
        if note:
            self._add(self._note_box(note))
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

    def _note_box(self, note: str) -> QFrame:
        """참고 메모: 드래그로 복사 가능, 속의 중국어는 누르면 바로 복사, [제안 반영해서 다시 만들기] 버튼."""
        box = QFrame()
        box.setObjectName("notebox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        lab = QLabel(note_html(note))
        lab.setObjectName("note")
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.RichText)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        lab.linkActivated.connect(self._copy_link)
        bl.addWidget(lab)
        row = QHBoxLayout()
        self._note_copied = QLabel("")
        self._note_copied.setObjectName("copied")
        row.addWidget(self._note_copied, 1)
        if self._on_apply:
            apply = QPushButton("이 제안 반영해서 다시 만들기")
            apply.setObjectName("apply")
            apply.setCursor(Qt.PointingHandCursor)
            apply.clicked.connect(lambda: self._on_apply(note))
            row.addWidget(apply)
        bl.addLayout(row)
        return box

    def _copy_link(self, href: str):
        from urllib.parse import unquote
        text = unquote(href[5:]) if href.startswith("copy:") else ""
        if text and self._on_copy:
            self._on_copy(text)
            self._note_copied.setText(f"✓ '{text}' 복사됨")

    def show_similar(self, mine: str, past_mine: str, options: list, on_new):
        """전에 비슷하게 보낸 말이 있을 때: AI를 쓰기 전에 그 문장들을 먼저 보여 줌 (무료)."""
        self._close_timer.stop()
        self._clear()
        self._add(self._label("내가 쓴 말", "mine"))
        self._add(self._label(mine, "ctitle", wrap=True))
        info = QFrame()
        info.setObjectName("notebox")
        il = QVBoxLayout(info)
        il.setContentsMargins(12, 8, 12, 8)
        il.addWidget(self._label("전에 비슷하게 보낸 말 (저장소에서, 무료)\n“" + past_mine + "”", "note", wrap=True))
        self._add(info)
        for i, opt in enumerate(options):
            w = _Option(opt, best=(i == 0))
            w.clicked.connect(self._picked)
            self._add(w)
        self.body.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        new = QPushButton("새로 만들기 (AI 사용)")
        new.setObjectName("apply")
        new.clicked.connect(on_new)
        row.addWidget(new)
        holder = QWidget()
        holder.setLayout(row)
        self._add(holder)

    def mark_text(self, chinese: str):
        """이미 고른 문장에 '복사됨' 표시 (후보를 다시 그려도 고른 표시 유지)."""
        for o in self._widgets:
            if isinstance(o, _Option):
                o.set_picked(o.opt.get("chinese") == chinese)

    def mark_first(self):
        """추천(첫 번째) 문장은 미리 복사해 두었다는 표시 (창은 닫지 않음)."""
        first = next((o for o in self._widgets if isinstance(o, _Option)), None)
        if first:
            first.set_picked(True)

    def show_reading(self, zh: str, ko: str, nuance: str = "", title: str = "원문",
                     intent_state: str = "", on_intent=None):
        """말풍선을 눌렀을 때·업체 글을 복사(Ctrl+C)했을 때: 원문과 번역, 속뜻을 크게."""
        self._close_timer.stop()
        self._clear()
        self._add(self._label(title, "mine"))
        zh_lab = self._label(zh, "ctitle", wrap=True)
        zh_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._add(zh_lab)
        self._add(self._label("번역", "mine"))
        ko_lab = self._label(ko, "zh", wrap=True)
        ko_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._add(ko_lab)
        if nuance:
            box = QFrame()
            box.setObjectName("notebox")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 8, 12, 8)
            lab = self._label("💡 속뜻\n" + nuance, "note", wrap=True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bl.addWidget(lab)
            self._add(box)
        elif intent_state == "wait":
            self._add(self._label("💡 속뜻 분석 중…", "mine"))
        elif intent_state == "ask" and on_intent:
            # 속뜻은 궁금할 때만 (누를 때만 AI 사용)
            row = QHBoxLayout()
            btn = QPushButton("🔍 속뜻 자세히 보기")
            btn.setObjectName("apply")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(on_intent)
            row.addWidget(btn)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            self._add(holder)
        self.body.addStretch(1)

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
