"""대화방별 대화 저장: 껐다 켜도 전에 본 화면은 글자 인식 없이 바로, 새 부분만 읽기."""
import os

import numpy as np
import pytest
from PIL import Image

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "real_gabang.png")


@pytest.fixture()
def reader_factory(tmp_path, monkeypatch):
    if not os.path.exists(FIX):
        pytest.skip("개인 화면 자료 없음")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from app.config import DEFAULTS
    from app.screen_reader import ScreenReader

    def make():
        r = ScreenReader(dict(DEFAULTS), None, lambda: None)
        try:
            r._get_ocr()
        except Exception as e:
            pytest.skip(f"글자 인식 사용 불가: {e}")
        return r
    return make


def kinds(items):
    return [(i.kind, i.side, i.text) for i in items]


def test_restart_shows_stored_room_instantly(reader_factory):
    img = Image.open(FIX).convert("RGB")
    r1 = reader_factory()
    res = r1.scan_image(img)
    r1._last_res = res
    r1._room_update(img, res, known=False)
    r1._store.save(force=True)

    r2 = reader_factory()                       # 번역기를 껐다 켬
    room, restored, roi = r2._restore_from_store(img)
    # 같은 화면 → 글자 인식이 필요 없거나, 화면 끝에 잘려 보이는 작은 부분만 다시 읽음
    assert roi is None or roi[1] - roi[0] < (res.chat_bottom - res.chat_top) * 0.15
    want = [k for k, it in zip(kinds(res.items), res.items) if not it.extra.get("cut")]
    got = [k for k, it in zip(kinds(restored.items), restored.items) if not it.extra.get("cut")]
    assert got == want and restored.vendor == res.vendor


def test_new_messages_only_new_part_is_read(reader_factory):
    img = Image.open(FIX).convert("RGB")
    r1 = reader_factory()
    res = r1.scan_image(img)
    r1._last_res = res
    r1._room_update(img, res, known=False)
    r1._store.save(force=True)
    # 새 메시지가 와서 내용이 위로 dy 만큼 올라감 → 아래쪽만 새로 읽으면 됨
    dy = 120
    arr = np.asarray(img).copy()
    top, bottom = res.chat_top + 1, res.chat_bottom - 1
    arr[top:bottom - dy] = np.asarray(img)[top + dy:bottom]
    arr[bottom - dy:bottom] = (250, 250, 250)
    r2 = reader_factory()
    room, restored, roi = r2._restore_from_store(Image.fromarray(arr))
    assert roi is not None and roi[0] >= bottom - dy - 80 and roi[1] <= res.chat_bottom
