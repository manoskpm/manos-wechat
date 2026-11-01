"""위챗 옆에 붙는 세로 번역 패널 화면."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import uuid
from tkinter import messagebox, simpledialog

from . import config as C
from . import win_window
from .chat_parser import is_chinese_text, merge_into_history, similar
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
        self.last_clip = None
        self.own_clip = None
        self.translator = None
        self._last_geom = None
        self._raw_key = ""

        self._build()
        try:  # 프로그램을 켜기 전에 복사해 둔 글은 번역하지 않음
            self.last_clip = self.root.clipboard_get()
        except tk.TclError:
            pass
        self.set_vendor("")
        self.log_path = C.data_dir() / "log.txt"
        self.status_var.set("시작 중...")

        self.reader = ScreenReader(self.cfg, self._on_scan_thread, self._own_hwnd,
                                   log_path=self.log_path)
        self.reader.start()

        # 반복 작업을 먼저 시작하고, API 키 확인은 그 다음에 (창이 멈추지 않게)
        self._every(100, self._drain_queue)
        self._every(500, self._dock_tick)
        self._every(800, self._clipboard_tick)
        self._every(1000, self._status_tick)
        self.root.after(300, self._ensure_api_key)

    # ------------------------------------------------------------ 공통 도구
    def _every(self, ms, fn):
        """fn 을 ms 마다 실행. 한 번 오류가 나도 멈추지 않고 기록만 남김."""
        def run():
            try:
                fn()
            except Exception:
                self._write_log(f"{fn.__name__} 오류\n{traceback.format_exc()}")
            finally:
                self.root.after(ms, run)
        self.root.after(ms, run)

    def _write_log(self, msg):
        try:
            with open(self.log_path, "a", encoding="utf-8") as fp:
                fp.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def _dialog(self, fn, *args, **kwargs):
        """질문 창이 '항상 위' 패널 뒤에 숨지 않도록 잠시 패널의 '항상 위'를 끔."""
        self.root.attributes("-topmost", False)
        try:
            return fn(*args, parent=self.root, **kwargs)
        finally:
            self.root.attributes("-topmost", True)

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

        inrow = tk.Frame(self.root, bg=BG)
        inrow.pack(fill="x", side="bottom", padx=8, pady=2)
        tk.Button(inrow, text="번역", font=(FONT, 10, "bold"), bg="#2563eb", fg="white",
                  activebackground="#1d4ed8", activeforeground="white", relief="flat",
                  command=self._send).pack(side="right", fill="y", padx=(4, 0))
        self.input = tk.Text(inrow, height=3, wrap="char", font=f, relief="solid", bd=1,
                             highlightthickness=2, highlightcolor="#3b82f6")
        self.input.pack(side="left", fill="x", expand=True)
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
        self.log.tag_config("click", foreground="#2563eb", underline=True)
        self.log.tag_config("right", justify="right")
        self.log.tag_bind("click", "<Enter>", lambda e: self.log.config(cursor="hand2"))
        self.log.tag_bind("click", "<Leave>", lambda e: self.log.config(cursor=""))
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
        key = self._dialog(simpledialog.askstring, "API 키", msg, show="*")
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
            self._dialog(messagebox.showinfo, "저장됨",
                         f"저장했습니다:\n{p}\n\n이 사진을 비서실장에게 보내 주시면 화면 인식을 맞춰 드립니다.")
            self._open(C.data_dir())
        else:
            self._dialog(messagebox.showinfo, "아직 없음",
                         "위챗 창을 찾지 못했습니다. 위챗을 켜 두고 다시 눌러 주세요.")

    def _save_tone(self):
        self.cfg["tone"] = self.tone_var.get()
        C.save_config(self.cfg)

    def _save_toggles(self):
        self.cfg["auto_read"] = self.auto_var.get()
        self.cfg["dock"] = self.dock_var.get()
        self.reader.enabled = self.cfg["auto_read"]
        C.save_config(self.cfg)

    def _ask_vendor(self):
        name = self._dialog(
            simpledialog.askstring, "거래처 이름", "이 대화방을 패널에 어떤 이름으로 표시할까요?\n"
            "(바꾼 이름은 기억해 두었다가 다음에도 자동으로 씁니다)",
            initialvalue=self.vendor)
        if name is None or not name.strip() or name.strip() == self.vendor:
            return
        name = name.strip()
        old = self.vendor
        if self._raw_key:
            self.cfg.setdefault("aliases", {})[self._raw_key] = name
            C.save_config(self.cfg)
        C.rename_history(old or "_미지정", name)
        self.set_vendor(name)

    # ------------------------------------------------------------ 거래처 / 기록
    def set_vendor(self, vendor: str):
        self.vendor = vendor
        self.vendor_var.set(vendor or "위챗 대화방을 클릭하세요")
        self.history = C.load_history(vendor or "_미지정")
        for h in self.history:
            h.setdefault("id", uuid.uuid4().hex)
        self._render_all()

    def _save(self):
        C.save_history(self.vendor or "_미지정", self.history)

    def _render_all(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        for h in self.history[-80:]:
            self._render(h)
        self.log.config(state="disabled")
        self.log.see("end")

    def _render(self, h: dict):
        """메시지 하나를 패널에 표시 (번역 안 된 메시지는 클릭하면 번역)."""
        log = self.log
        if h["side"] == "in":
            log.insert("end", "업체\n", "label")
            log.insert("end", h["zh"] + "\n", "zh")
        else:
            log.insert("end", "나\n", ("label", "right"))
            if h.get("src") == "panel":
                log.insert("end", h.get("ko", "") + "\n", ("out_ko", "right"))
            log.insert("end", h["zh"] + "\n", ("out_zh", "right"))
        translated = h.get("ko") if h["side"] == "in" or h.get("src") != "panel" else True
        if h.get("pending"):
            log.insert("end", "번역 중...\n", "label")
        elif not translated:
            tag = "tr_" + h["id"]
            log.insert("end", "🌐 눌러서 번역\n", ("click", tag) + (("right",) if h["side"] == "out" else ()))
            log.tag_bind(tag, "<Button-1>", lambda e, i=h["id"]: self._translate_entry_by_id(i))
        elif h["side"] == "in":
            log.insert("end", h["ko"] + "\n", "in_ko")
            if h.get("nuance"):
                mark = "💡 " if h.get("certainty") == "high" else "💡(추정) "
                log.insert("end", mark + h["nuance"] + "\n", "nuance")
        elif h.get("src") != "panel":
            log.insert("end", h["ko"] + "\n", ("out_ko", "right"))
        log.insert("end", "\n")

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

    def _resolve_vendor(self, res) -> str:
        """대화방 이름 정하기: 한국어로 읽은 이름 → 제목 모양으로 기억한 이름 → 새 대화방."""
        from .screen_reader import signature_distance
        cfg = self.cfg
        changed = False
        registry = cfg.setdefault("title_map", [])
        best = min(registry, default=None, key=lambda e: signature_distance(e["sig"], res.title_sig))
        best_ok = best is not None and signature_distance(best["sig"], res.title_sig) <= 5.0
        raw = res.title_text or res.vendor
        if raw:
            known = cfg.setdefault("known_vendors", [])
            canon = next((k for k in known if similar(k, raw, 0.8)), None)
            if canon is None:
                canon = raw
                known.append(raw)
                changed = True
            if best_ok and best["name"] != canon:
                best["name"] = canon
                changed = True
            elif not best_ok:
                registry.append({"sig": res.title_sig, "name": canon})
                changed = True
        elif best_ok:
            canon = best["name"]
        else:
            canon = f"대화방 {len(registry) + 1}"
            registry.append({"sig": res.title_sig, "name": canon})
            changed = True
            self.root.after(200, lambda: self._hint(
                f"대화방 이름을 읽지 못해 '{canon}'(으)로 저장했습니다. 위의 [거래처 변경]으로 이름을 바꿀 수 있어요."))
        if changed:
            cfg["title_map"] = registry[-300:]
            C.save_config(cfg)
        self._raw_key = canon
        return cfg.get("aliases", {}).get(canon, canon)

    def _handle_scan(self, res):
        vendor = self._resolve_vendor(res)
        if vendor != self.vendor:
            self.set_vendor(vendor)
        hist, auto = merge_into_history(self.history, res.bubbles, max_auto=3)
        if len(hist) != len(self.history):
            now = time.strftime("%Y-%m-%d %H:%M")
            for h in hist:
                h.setdefault("id", uuid.uuid4().hex)
                h.setdefault("t", now)
            self.history = hist
            self._save()
            self._render_all()
        for e in auto:  # 새로 온 업체 메시지만 자동 번역 (옛날 메시지는 눌러야 번역)
            self._translate_entry(e)

    def _translate_entry_by_id(self, entry_id):
        entry = next((h for h in self.history if h.get("id") == entry_id), None)
        if entry and not entry.get("pending"):
            self._translate_entry(entry)

    def _translate_entry(self, entry):
        """기록에 있는 중국어 메시지(업체 것 또는 내가 위챗에 직접 쓴 것)를 한국어로 번역."""
        if not self.translator:
            self._log_error("API 키가 없습니다. ⚙ 메뉴에서 API 키를 넣어 주세요.")
            return
        entry["pending"] = True
        self._render_all()
        self._translate_async("in", entry["zh"], entry_id=entry["id"])

    def _translate_async(self, direction, text, tone="polite", entry_id=None):
        if not self.translator:
            self._log_error("API 키가 없습니다. ⚙ 메뉴에서 API 키를 넣어 주세요.")
            return
        vendor = self.vendor
        history = [h for h in self.history if h.get("ko") and h.get("id") != entry_id]
        req = build_request(cfg=self.cfg, user_instructions=C.load_user_instructions(), vendor=vendor,
                            history=history, direction=direction, text=text, tone=tone)

        def work():
            try:
                self.q.put(("done", direction, vendor, entry_id, text, self.translator.run(req)))
            except TranslateError as e:
                self.q.put(("error", str(e), vendor, entry_id))
            except Exception as e:  # 예상 못 한 오류도 화면에 표시
                self.q.put(("error", f"알 수 없는 오류: {e}", vendor, entry_id))

        self.status_var.set("번역 중...")
        threading.Thread(target=work, daemon=True).start()

    def _history_of(self, vendor):
        return self.history if vendor == self.vendor else C.load_history(vendor or "_미지정")

    def _store(self, vendor, hist):
        if vendor == self.vendor:
            self.history = hist
            self._save()
            self._render_all()
        else:  # 번역 중에 대화방이 바뀐 경우 원래 거래처 기록에 저장
            C.save_history(vendor or "_미지정", hist)

    def _handle_done(self, direction, vendor, entry_id, text, data):
        hist = self._history_of(vendor)
        if direction == "in":
            entry = next((h for h in hist if h.get("id") == entry_id), None)
            if entry is None:
                return
            entry.pop("pending", None)
            entry.update(ko=data.get("korean", ""), nuance=data.get("nuance", ""),
                         certainty=data.get("certainty", "none"))
            if entry["side"] == "out":
                entry["nuance"] = ""
        else:
            entry = {"id": uuid.uuid4().hex, "t": time.strftime("%Y-%m-%d %H:%M"), "side": "out",
                     "src": "panel", "ko": text, "zh": data.get("chinese", ""),
                     "back": data.get("back_translation", ""), "note": data.get("note", "")}
            hist.append(entry)
            self._show_result(entry)
        self._store(vendor, hist)

    def _handle_error(self, msg, vendor, entry_id):
        self._log_error(msg)
        if entry_id:
            hist = self._history_of(vendor)
            for h in hist:
                if h.get("id") == entry_id:
                    h.pop("pending", None)
            self._store(vendor, hist)

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
                    self._handle_error(*item[1:])
                    if self.res_zh.cget("text") == "번역 중...":
                        self.res_zh.config(text="")
                    self.status_var.set("")
        except queue.Empty:
            pass

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
                    own = self._own_hwnd()
                    if sys.platform == "win32" and own:
                        # 제목줄까지 포함해서 위챗과 위아래 끝이 딱 맞게
                        win_window.place_visible(own, x, t, w, b - t)
                    else:
                        self.root.geometry(geom)
                    self._last_geom = geom
                    self._write_log(f"dock wechat={(l, t, r, b)} screen={sw} panel={geom}")

    def _clipboard_tick(self):
        if self.cfg.get("clipboard_watch", True):
            try:
                clip = self.root.clipboard_get()
            except tk.TclError:
                clip = None
            if clip and clip != self.last_clip:
                self.last_clip = clip
                if clip != self.own_clip and is_chinese_text(clip):
                    # 복사한 중국어: 기록에 있는 메시지면 그 메시지를, 없으면 새 업체 메시지로 추가해서 번역
                    clip = clip.strip()
                    entry = next((h for h in reversed(self.history) if similar(h["zh"], clip)), None)
                    if entry is None:
                        entry = {"id": uuid.uuid4().hex, "t": time.strftime("%Y-%m-%d %H:%M"),
                                 "side": "in", "zh": clip, "ko": ""}
                        self.history.append(entry)
                        self._save()
                    if not entry.get("ko") and not entry.get("pending"):
                        self._translate_entry(entry)

    def _status_tick(self):
        if not self.status_var.get().startswith("번역"):
            self.status_var.set(self.reader.status)

    def quit(self):
        self.reader.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
