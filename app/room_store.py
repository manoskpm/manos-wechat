"""대화방별 대화 저장소 (카카오톡처럼): 스크롤해서 본 대화를 대화방마다 순서대로 기억.

- 덩어리(말풍선·사진·시간 줄 …)를 '대화 기준 위치'로 저장 → 다시 열거나, 위로 스크롤하거나,
  번역기를 껐다 켜도 전에 본 부분은 글자 인식 없이 바로 보여 줌.
- 글자와 위치만 저장해서 용량이 아주 작음 (프로필 사진만 대화방마다 한 장씩).
- 이 컴퓨터 안에만 저장: %APPDATA%\\ManosWeChatTranslator\\rooms
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import time

import numpy as np

from . import config as C
from .segment import Item

MAX_ITEMS = 3000   # 대화방 하나에 기억하는 덩어리 수 (오래된 것부터 정리)


def _merge_ranges(ranges):
    out = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 2:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class Room:
    """대화방 하나. 위치는 '대화 기준'(스크롤과 상관없는 고정 위치) = 화면 위치 - shift."""

    def __init__(self, sig, geom):
        self.sig = list(sig)
        self.geom = tuple(geom)       # (창 높이, 대화 영역 왼쪽, 오른쪽, 위, 아래) — 바뀌면 위치가 안 맞음
        self.shift = 0                # 지금 화면 = 대화 기준 위치 + shift
        self.items: list[dict] = []   # 대화 기준 위치로 저장한 덩어리
        self.covered: list = []       # 읽어 둔 구간 [(위, 아래)] (대화 기준)
        self.header: dict = {}        # 대화방 이름·제목 줄 등 (번역창 위쪽에 필요한 것)
        self.profile = None           # 마지막 화면의 줄별 밝기 (다시 열었을 때 위치 맞추기)
        self.profile_shift = 0
        self.avatars: dict = {}       # 쪽(in/out) → 프로필 사진 png
        self.dirty = False

    # ---- 저장된 덩어리 → 지금 화면 ----
    def view(self, top: int, bottom: int, shift: int | None = None) -> list:
        sh = self.shift if shift is None else shift
        out = []
        for d in self.items:
            y0, y1 = d["y0"] + sh, d["y1"] + sh
            if y1 <= top or y0 >= bottom:
                continue
            it = Item(d["kind"], d["side"], y0, y1, d["x0"], d["x1"], d["text"])
            it.extra = dict(d.get("extra", {}))
            if "avatar" in it.extra:
                ax0, ay0, ax1, ay1 = it.extra["avatar"]
                it.extra["avatar"] = (ax0, ay0 + sh, ax1, ay1 + sh)
                png = self.avatars.get(d["side"])
                if png:
                    it.extra["avatar_png"] = png
            if y0 <= top + 6 or y1 >= bottom - 6:
                it.extra["cut"] = True
            out.append(it)
        return out

    def covers(self, a: int, b: int) -> bool:
        """화면 구간 [a, b) 를 전에 읽어 둔 적이 있는지."""
        a, b = a - self.shift, b - self.shift
        return any(x <= a and b <= y for x, y in self.covered)

    # ---- 지금 화면 → 저장 ----
    def merge(self, res):
        """읽은 화면 결과를 저장소에 합침 (화면에 보이는 구간은 새 결과로 바꿈)."""
        top, bottom = res.chat_top, res.chat_bottom
        good = [it for it in res.items if not it.extra.get("cut")]
        lo = max([top + 6] + [it.y1 for it in res.items if it.extra.get("cut") and it.y0 <= top + 6])
        hi = min([bottom - 6] + [it.y0 for it in res.items if it.extra.get("cut") and it.y1 >= bottom - 6])
        if hi <= lo:
            return
        A, B = lo - self.shift, hi - self.shift
        keep = [d for d in self.items if d["y1"] <= A or d["y0"] >= B]
        for it in good:
            if it.y0 < lo or it.y1 > hi:
                continue
            d = {"kind": it.kind, "side": it.side, "y0": it.y0 - self.shift, "y1": it.y1 - self.shift,
                 "x0": it.x0, "x1": it.x1, "text": it.text,
                 "extra": {k: v for k, v in it.extra.items() if k not in ("avatar_png", "cut")}}
            if "avatar" in d["extra"]:
                ax0, ay0, ax1, ay1 = d["extra"]["avatar"]
                d["extra"]["avatar"] = (ax0, ay0 - self.shift, ax1, ay1 - self.shift)
                if it.extra.get("avatar_png"):
                    self.avatars[it.side] = it.extra["avatar_png"]
            if "bg" in d["extra"]:
                d["extra"]["bg"] = tuple(int(v) for v in d["extra"]["bg"])
            keep.append(d)
        keep.sort(key=lambda d: d["y0"])
        if len(keep) > MAX_ITEMS:
            keep = keep[-MAX_ITEMS:]
        self.items = keep
        self.covered = _merge_ranges(self.covered + [(A, B)])
        self.header = {k: getattr(res, k) for k in
                       ("vendor", "title_text", "chat_left", "chat_right", "title_h", "band_h", "chat_top",
                        "chat_bottom", "win_h", "chat_bg", "frame_rgb")}
        self.header["title_png"] = base64.b64encode(res.title_png or b"").decode("ascii")
        self.header["title_sig"] = list(res.title_sig or [])
        self.dirty = True

    def align(self, res) -> bool:
        """위치를 모르는 화면(껐다 켠 뒤, 맨 아래로 점프 등): 같은 글이 있는 말풍선으로 위치를 맞춤."""
        texts = {}
        for d in self.items:
            if d["kind"] == "text" and len(d["text"]) >= 4:
                texts.setdefault(d["text"], []).append(d)
        votes = {}
        for it in res.items:
            if it.kind != "text" or it.extra.get("cut") or len(it.text) < 4:
                continue
            for d in texts.get(it.text, []):
                sh = it.y0 - d["y0"]
                votes[sh // 4] = votes.get(sh // 4, 0) + 1
        if not votes:
            return False
        best = max(votes, key=votes.get)
        if votes[best] < 1:
            return False
        cands = [it.y0 - d["y0"] for it in res.items if it.kind == "text" and not it.extra.get("cut")
                 for d in texts.get(it.text, []) if (it.y0 - d["y0"]) // 4 == best]
        self.shift = int(np.median(cands))
        return True

    def restored_result(self, res_template, shift: int):
        """저장된 대화로 지금 화면 결과를 바로 만듦 (글자 인식 없이)."""
        r = copy.copy(res_template)
        r.items = self.view(r.chat_top, r.chat_bottom, shift)
        return r

    # ---- 파일 ----
    def to_json(self) -> dict:
        prof = None
        if self.profile is not None:
            p = np.clip(self.profile, 0, 255).astype(np.uint8)
            prof = {"shape": list(p.shape), "data": base64.b64encode(p.tobytes()).decode("ascii")}
        return {"sig": self.sig, "geom": list(self.geom), "shift": self.shift, "items": self.items,
                "covered": self.covered, "header": self.header, "profile": prof,
                "profile_shift": self.profile_shift,
                "avatars": {k: base64.b64encode(v).decode("ascii") for k, v in self.avatars.items()},
                "saved": time.strftime("%Y-%m-%d %H:%M")}

    @classmethod
    def from_json(cls, d: dict) -> "Room":
        r = cls(d["sig"], d["geom"])
        r.shift = d.get("shift", 0)
        r.items = d.get("items", [])
        for it in r.items:
            ex = it.get("extra", {})
            if "avatar" in ex:
                ex["avatar"] = tuple(ex["avatar"])
            if "bg" in ex:
                ex["bg"] = tuple(ex["bg"])
        r.covered = [list(c) for c in d.get("covered", [])]
        r.header = d.get("header", {})
        p = d.get("profile")
        if p:
            r.profile = np.frombuffer(base64.b64decode(p["data"]), dtype=np.uint8).reshape(p["shape"]).astype(
                np.float32)
        r.profile_shift = d.get("profile_shift", 0)
        r.avatars = {k: base64.b64decode(v) for k, v in d.get("avatars", {}).items()}
        return r


class RoomStore:
    def __init__(self):
        self.rooms: list[Room] = []
        self._saved_at = 0.0
        self._dir = C.data_dir() / "rooms"
        try:
            self._dir.mkdir(exist_ok=True)
            for f in sorted(self._dir.glob("*.json"), key=lambda f: f.stat().st_mtime):
                try:
                    self.rooms.append(Room.from_json(json.loads(f.read_text(encoding="utf-8"))))
                except (OSError, ValueError, KeyError):
                    continue
        except OSError:
            pass

    def find(self, sig, same) -> Room | None:
        return next((r for r in reversed(self.rooms) if same(r.sig, sig)), None)

    def get(self, sig, geom, same) -> Room:
        r = self.find(sig, same)
        if r is None:
            r = Room(sig, geom)
            self.rooms.append(r)
        elif tuple(r.geom) != tuple(geom):
            # 창 크기가 바뀌면 저장된 위치가 안 맞으므로 그 방의 화면 정보만 새로 시작 (번역은 따로 남아 있음)
            r.__init__(sig, geom)
        return r

    def save(self, force: bool = False):
        if not force and time.time() - self._saved_at < 3:
            return
        self._saved_at = time.time()
        for r in self.rooms:
            if not r.dirty:
                continue
            name = hashlib.md5(bytes(v // 255 for v in r.sig)).hexdigest()[:16]
            try:
                (self._dir / f"{name}.json").write_text(json.dumps(r.to_json(), ensure_ascii=False),
                                                       encoding="utf-8")
                r.dirty = False
            except (OSError, TypeError, ValueError):
                pass
