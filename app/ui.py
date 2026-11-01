"""위챗 옆에 붙는 세로 번역 패널 화면."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

from . import config as C
from . import win_window
from .chat_parser import find_new_incoming, is_chinese_text, similar
from .prompts import TONES
from .screen_reader import ScreenReader
from .translator import TranslateError, Translator, build_request

FONT = "Malgun Gothic" if sys.platform == "win32" else "TkDefaultFont"
BG = "#ffffff"
LOG_BG = "#f7f8fa"
BLUE = "#2563eb"
GREEN = "#15803d"
ORANGE = "#b45309"
GRAY = "#6b7280"


class App:
    def __init__(self):
        self.cfg = C.load_config()
        self.root = tk.Tk()
        self.root.title("발주 번역기")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        # 화면 배율(125%, 150%)에 맞춰 패널 폭도 키움
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.pw = int(self.cfg["panel_width"] * self.scale)
        self.root.geometry(f"{self.pw}x{int(760 * self.scale)}+100+100")
        self.root.minsize(int(320 * self.scale), int(520 * self.scale))
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.q: queue.Queue = queue.Queue()
        self.vendor = ""
        self.history: list[dict] = []
        self.session_seen: dict[str, list[str]] = {}
        self.last_clip = None
        self.own_clip = None
        self.translator = None
        self._last_geom = None
        self.title_sig = None
        self._unknown_hint_shown = False

        self._build()
        try:  # 프로그램을 켜기 전에 복사해 둔 글은 번역하지 않음
            self.last_clip = self.root.clipboard_get()
        except tk.TclError:
            pass
        self._ensure_api_key()
        self.set_vendor("")

        self.reader = ScreenReader(self.cfg, self._on_scan_thread, self._own_hwnd,
                                   log_path=C.data_dir() / "log.txt")
        self.reader.start()

        self.root.after(100, self._drain_queue)
        self.root.after(500, self._dock_tick)
        self.root.after(800, self._clipboard_tick)
        self.root.after(1000, self._status_tick)

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        f = (FONT, 10)
        top = tk.Frame(self.root, bg="#2f3542")
        top.pack(fill="x")
        self.vendor_var = tk.StringVar()
        tk.Label(top, textvariable=self.vendor_var, fg="white", bg="#2f3542",
                 font=(FONT, 11, "bold"), anchor="w").pack(side="left", padx=8, pady=6)
        tk.Button(top, text="⚙", command=self._settings_menu, relief="flat", bg="#2f3542",
                  fg="white", activebackground="#57606f").pack(side="right", padx=4)
        tk.Button(top, text="거래처 변경", command=self._ask_vendor, relief="flat", bg="#2f3542",
                  fg="#cbd5e1", activebackground="#57606f", font=(FONT, 9)).pack(side="right")

        opts = tk.Frame(self.root, bg=BG)
        opts.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(opts, text="말투", bg=BG, font=f, fg=GRAY).pack(side="left")
        self.tone_var = tk.StringVar(value=self.cfg.get("tone", "polite"))
        for key, (label, _) in TONES.items():
            tk.Radiobutton(opts, text=label, value=key, variable=self.tone_var, bg=BG, font=f,
                           indicatoron=False, padx=8, selectcolor="#dbeafe",
                           command=self._save_tone).pack(side="left", padx=2)
        self.auto_var = tk.BooleanVar(value=self.cfg.get("auto_read", True))
        self.dock_var = tk.BooleanVar(value=self.cfg.get("dock", True))
        tk.Checkbutton(opts, text="옆에 붙기", variable=self.dock_var, bg=BG, font=(FONT, 9),
                       command=self._save_toggles).pack(side="right")
        tk.Checkbutton(opts, text="자동 읽기", variable=self.auto_var, bg=BG, font=(FONT, 9),
                       command=self._save_toggles).pack(side="right")

        # 아래쪽(상태줄, 결과, 입력창, 문장 버튼)을 먼저 배치해야 창이 작아도 잘리지 않음
        self.status_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.status_var, bg="#eef2f7", fg=GRAY, font=(FONT, 8),
                 anchor="w").pack(fill="x", side="bottom")

        wrap = self.pw - int(40 * self.scale)
        res = tk.Frame(self.root, bg="#fff8e6", highlightbackground="#f5d27a", highlightthickness=1)
        res.pack(fill="x", side="bottom", padx=8, pady=(4, 4))
        self.res_zh = tk.Label(res, text="", bg="#fff8e6", font=(FONT, 10, "bold"),
                               justify="left", anchor="w", wraplength=wrap)
        self.res_zh.pack(fill="x", padx=6, pady=(4, 0))
        self.res_back = tk.Label(res, text="", bg="#fff8e6", fg=GRAY, font=(FONT, 8),
                                 justify="left", anchor="w", wraplength=wrap)
        self.res_back.pack(fill="x", padx=6)
        row = tk.Frame(res, bg="#fff8e6")
        row.pack(fill="x", padx=6, pady=4)
        self.copy_lbl = tk.Label(row, text="번역된 중국어가 여기에 나옵니다", bg="#fff8e6", fg=ORANGE,
                                 font=(FONT, 9, "bold"))
        self.copy_lbl.pack(side="left")
        tk.Button(row, text="다시 복사", font=(FONT, 8), command=self._recopy).pack(side="right")

        self.input = tk.Text(self.root, height=3, wrap="char", font=f, relief="solid", bd=1,
                             highlightthickness=2, highlightcolor="#3b82f6")
        self.input.pack(fill="x", side="bottom", padx=8, pady=2)
        self.input.bind("<Return>", self._on_enter)
        self.input.bind("<Shift-Return>", lambda e: None)
        tk.Label(self.root, text="한국어로 쓰고 Enter (줄바꿈: Shift+Enter)", bg=BG, fg=GRAY,
                 font=(FONT, 8), anchor="w").pack(fill="x", side="bottom", padx=8, pady=(6, 0))

        chips = tk.Frame(self.root, bg=BG)
        chips.pack(fill="x", side="bottom", padx=8)
        for i, phrase in enumerate(self.cfg.get("quick_phrases", [])):
            tk.Button(chips, text=phrase, font=(FONT, 8), relief="groove", bg="#f1f3f5",
                      command=lambda p=phrase: self._insert_phrase(p)).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        chips.columnconfigure(0, weight=1)
        chips.columnconfigure(1, weight=1)

        # 대화 기록은 남는 공간을 모두 차지
        logf = tk.Frame(self.root, bg=BG)
        logf.pack(fill="both", expand=True, padx=8, pady=4)
        sb = tk.Scrollbar(logf)
        sb.pack(side="right", fill="y")
        self.log = tk.Text(logf, wrap="char", bg=LOG_BG, relief="flat", font=f, height=5,
                           yscrollcommand=sb.set, padx=8, pady=6, spacing1=2, spacing3=2)
        self.log.pack(side="left", fill="both", expand=True)
        sb.config(command=self.log.yview)
        self.log.tag_config("label", foreground=GRAY, font=(FONT, 8))
        self.log.tag_config("zh", foreground="#111827")
        self.log.tag_config("in_ko", foreground=BLUE, font=(FONT, 10, "bold"))
        self.log.tag_config("nuance", foreground=ORANGE, lmargin1=8, lmargin2=8)
        self.log.tag_config("out_ko", foreground=GRAY)
        self.log.tag_config("out_zh", foreground=GREEN, font=(FONT, 10, "bold"))
        self.log.tag_config("err", foreground="#dc2626")
        self.log.tag_config("hint", foreground="#7c3aed")
        self.log.config(state="disabled")

    # ------------------------------------------------------------ 설정
    def _ensure_api_key(self):
        if not self.cfg.get("api_key"):
            self._ask_api_key(first=True)
        if self.cfg.get("api_key"):
            self.translator = Translator(self.cfg["api_key"])

    def _ask_api_key(self, first=False):
        msg = ("Claude API 키를 붙여넣어 주세요.\n(sk-ant- 로 시작합니다. 이 컴퓨터에만 저장됩니다)"
               if first else "새 Claude API 키를 붙여넣어 주세요.")
        key = simpledialog.askstring("API 키", msg, parent=self.root, show="*")
        if key and key.strip():
            self.cfg["api_key"] = key.strip()
            C.save_config(self.cfg)
            self.translator = Translator(self.cfg["api_key"])

    def _settings_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="내 지시문·용어 편집", command=lambda: self._open(C.instructions_path()))
        m.add_command(label="API 키 변경", command=self._ask_api_key)
        m.add_command(label="화면 인식 확인용 사진 저장", command=self._save_debug)
        m.add_command(label="데이터 폴더 열기", command=lambda: self._open(C.data_dir()))
        m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def _open(self, path):
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - 사용자가 직접 누른 메뉴
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _save_debug(self):
        p = C.data_dir() / "screen_check.png"
        if self.reader.save_debug_image(p):
            messagebox.showinfo("저장됨", f"저장했습니다:\n{p}\n\n이 사진을 비서실장에게 보내 주시면 화면 인식을 맞춰 드립니다.")
            self._open(C.data_dir())
        else:
            messagebox.showinfo("아직 없음", "아직 읽은 화면이 없습니다. 위챗 대화방을 열어 두고 잠시 후 다시 눌러 주세요.")

    def _save_tone(self):
        self.cfg["tone"] = self.tone_var.get()
        C.save_config(self.cfg)

    def _save_toggles(self):
        self.cfg["auto_read"] = self.auto_var.get()
        self.cfg["dock"] = self.dock_var.get()
        self.reader.enabled = self.cfg["auto_read"]
        C.save_config(self.cfg)

    def _ask_vendor(self):
        name = simpledialog.askstring(
            "거래처", "지금 위챗에 열린 대화방의 거래처 이름을 입력하세요.\n"
            "(한 번 정하면 다음부터 이 대화방을 열 때 자동으로 바뀝니다)",
            parent=self.root, initialvalue=self.vendor)
        if name is None or not name.strip():
            return
        name = name.strip()
        if self.title_sig:
            from .screen_reader import signature_distance
            tm = [e for e in self.cfg.get("title_map", [])
                  if signature_distance(e["sig"], self.title_sig) > 6.0]
            tm.append({"sig": self.title_sig, "name": name})
            self.cfg["title_map"] = tm[-200:]
            C.save_config(self.cfg)
        self.set_vendor(name)

    # ------------------------------------------------------------ 거래처 / 기록
    def set_vendor(self, vendor: str):
        self.vendor = vendor
        self.vendor_var.set(vendor or "거래처 미지정")
        self.history = C.load_history(vendor or "_미지정")
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        for h in self.history[-20:]:
            self._render(h)

    def _save(self):
        C.save_history(self.vendor or "_미지정", self.history)

    def _render(self, h: dict):
        self.log.config(state="normal")
        if h["side"] == "in":
            self.log.insert("end", "업체 →\n", "label")
            self.log.insert("end", h["zh"] + "\n", "zh")
            self.log.insert("end", h.get("ko", "") + "\n", "in_ko")
            if h.get("nuance"):
                mark = "💡 " if h.get("certainty") == "high" else "💡(추정) "
                self.log.insert("end", mark + h["nuance"] + "\n", "nuance")
        else:
            self.log.insert("end", "→ 업체 (나)\n", "label")
            self.log.insert("end", h.get("ko", "") + "\n", "out_ko")
            self.log.insert("end", h["zh"] + "\n", "out_zh")
        self.log.insert("end", "\n")
        self.log.config(state="disabled")
        self.log.see("end")

    def _hint(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", "ℹ " + msg + "\n\n", "hint")
        self.log.config(state="disabled")
        self.log.see("end")

    def _log_error(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", "⚠ " + msg + "\n\n", "err")
        self.log.config(state="disabled")
        self.log.see("end")

    # ------------------------------------------------------------ 받은 메시지
    def _on_scan_thread(self, res):
        self.q.put(("scan", res))

    def _vendor_from_title(self, res):
        if res.vendor:
            return res.vendor
        from .screen_reader import signature_distance
        best = min(self.cfg.get("title_map", []), default=None,
                   key=lambda e: signature_distance(e["sig"], res.title_sig))
        if best and signature_distance(best["sig"], res.title_sig) <= 6.0:
            return best["name"]
        return None

    def _handle_scan(self, res):
        from .screen_reader import signature_distance
        same_room = signature_distance(res.title_sig, self.title_sig) <= 6.0
        self.title_sig = res.title_sig
        vendor = self._vendor_from_title(res)
        if vendor is not None:
            if not similar(vendor, self.vendor, 0.8):
                self.set_vendor(vendor)
        elif not same_room:
            self.set_vendor("")
            self._hint("이 대화방 이름은 글자로 읽지 못했습니다. 위의 [거래처 변경]을 눌러 "
                       "이름을 한 번만 정해 주세요. 다음부터는 자동으로 바뀝니다.")
        bubbles = res.bubbles
        key = self.vendor or "_미지정"
        seen = self.session_seen.setdefault(key, [])
        # 이미 번역한 업체 메시지 + 내가 보낸 중국어(입력창에 붙여넣은 글을 업체 글로 착각하지 않게)
        known = [h["zh"] for h in self.history] + seen
        all_new = find_new_incoming(bubbles, known, max_new=10_000)
        to_translate = all_new[-self.cfg.get("max_new_per_scan", 3):]
        seen.extend(all_new)  # 오래된 것은 번역하지 않고 '본 것'으로 처리
        for text in to_translate:
            self._translate_async("in", text)

    def _translate_async(self, direction, text, tone="polite"):
        if not self.translator:
            self._log_error("API 키가 없습니다. ⚙ 메뉴에서 API 키를 넣어 주세요.")
            return
        vendor, history = self.vendor, list(self.history)
        req = build_request(cfg=self.cfg, user_instructions=C.load_user_instructions(), vendor=vendor,
                            history=history, direction=direction, text=text, tone=tone)

        def work():
            try:
                self.q.put(("done", direction, vendor, text, self.translator.run(req)))
            except TranslateError as e:
                self.q.put(("error", str(e)))
            except Exception as e:  # 예상 못 한 오류도 화면에 표시
                self.q.put(("error", f"알 수 없는 오류: {e}"))

        self.status_var.set("번역 중...")
        threading.Thread(target=work, daemon=True).start()

    def _handle_done(self, direction, vendor, text, data):
        entry = {"t": time.strftime("%Y-%m-%d %H:%M")}
        if direction == "in":
            entry.update(side="in", zh=text, ko=data.get("korean", ""),
                         nuance=data.get("nuance", ""), certainty=data.get("certainty", "none"))
        else:
            entry.update(side="out", ko=text, zh=data.get("chinese", ""),
                         back=data.get("back_translation", ""), note=data.get("note", ""))
            self._show_result(entry)
        if vendor == self.vendor:
            self.history.append(entry)
            self._save()
            self._render(entry)
        else:  # 번역 중에 거래처가 바뀐 경우 원래 거래처 기록에 저장
            h = C.load_history(vendor or "_미지정")
            h.append(entry)
            C.save_history(vendor or "_미지정", h)

    # ------------------------------------------------------------ 보내는 메시지
    def _on_enter(self, event):
        if event.state & 0x0001:  # Shift+Enter → 줄바꿈
            return None
        # 한글 입력 중 마지막 글자가 확정되도록 아주 잠깐 기다렸다가 읽음
        self.root.after(30, self._send)
        return "break"

    def _send(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self.res_zh.config(text="번역 중...")
        self.res_back.config(text="")
        self.copy_lbl.config(text="")
        self._translate_async("out", text, tone=self.tone_var.get())

    def _insert_phrase(self, phrase):
        self.input.insert("end", phrase)
        self.input.focus_set()

    def _show_result(self, entry):
        self.res_zh.config(text=entry["zh"])
        back = "↩ " + entry.get("back", "")
        if entry.get("note"):
            back += "\n※ " + entry["note"]
        self.res_back.config(text=back)
        self._copy(entry["zh"])

    def _copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.own_clip = text
        self.last_clip = text
        self.copy_lbl.config(text="📋 복사됨 → 위챗 입력창에 Ctrl+V, Enter")

    def _recopy(self):
        t = self.res_zh.cget("text")
        if t and t != "번역 중...":
            self._copy(t)

    # ------------------------------------------------------------ 반복 작업
    def _drain_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "scan":
                    self._handle_scan(item[1])
                elif kind == "done":
                    self._handle_done(*item[1:])
                    self.status_var.set("")
                elif kind == "error":
                    self._log_error(item[1])
                    if self.res_zh.cget("text") == "번역 중...":
                        self.res_zh.config(text="")
                    self.status_var.set("")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _own_hwnd(self):
        try:
            return win_window.toplevel_of(self.root.winfo_id())
        except tk.TclError:
            return None

    def _dock_tick(self):
        if self.dock_var.get():
            found = win_window.find_wechat()
            if found:
                _, (l, t, r, b) = found
                w = self.pw
                sw, _ = win_window.screen_size()
                if r + w <= sw:
                    x = r                 # 위챗 오른쪽
                elif l - w >= 0:
                    x = l - w             # 오른쪽에 자리가 없으면 왼쪽
                else:
                    x = 0                 # 양쪽 다 자리가 없으면 화면 왼쪽 끝 (위챗 대화방 목록 위에 겹침)
                geom = f"{w}x{b - t}+{x}+{t}"
                if geom != self._last_geom:
                    self.root.geometry(geom)
                    self._last_geom = geom
        self.root.after(500, self._dock_tick)

    def _clipboard_tick(self):
        if self.cfg.get("clipboard_watch", True):
            try:
                clip = self.root.clipboard_get()
            except tk.TclError:
                clip = None
            if clip and clip != self.last_clip:
                self.last_clip = clip
                if clip != self.own_clip and is_chinese_text(clip):
                    known = [h["zh"] for h in self.history[-30:] if h["side"] == "in"]
                    if not any(similar(clip, k) for k in known):
                        self.session_seen.setdefault(self.vendor or "_미지정", []).append(clip)
                        self._translate_async("in", clip.strip())
        self.root.after(800, self._clipboard_tick)

    def _status_tick(self):
        if not self.status_var.get().startswith("번역"):
            self.status_var.set(self.reader.status)
        self.root.after(1000, self._status_tick)

    def quit(self):
        self.reader.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
