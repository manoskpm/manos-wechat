from app.updater import parse_version, pick_update

REL = {"tag_name": "v12", "body": "변경 내용",
       "assets": [{"name": "ManosTranslator.exe", "browser_download_url": "https://x/ManosTranslator.exe"}]}


def test_parse_version():
    assert parse_version("v12") == 12 and parse_version("7") == 7
    assert parse_version("dev") is None and parse_version(None) is None


def test_pick_update():
    assert pick_update(REL, 11)["version"] == 12
    assert pick_update(REL, 12) is None
    assert pick_update({**REL, "assets": []}, 1) is None


def test_pending_update(tmp_path, monkeypatch):
    """미리 받아 둔 새 버전: 지금보다 새것일 때만 적용 대상, 오래된 건 정리."""
    import json
    import sys
    from app import updater
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ManosTranslator.exe"))
    monkeypatch.setattr(updater, "VERSION", "20")
    assert updater.pending_update() is None
    (tmp_path / updater.NEW_NAME).write_bytes(b"x")
    (tmp_path / updater.MARK_NAME).write_text(json.dumps({"version": 21}))
    assert updater.pending_update() == (str(tmp_path / updater.NEW_NAME), 21)
    (tmp_path / updater.MARK_NAME).write_text(json.dumps({"version": 20}))   # 이미 적용된 버전
    assert updater.pending_update() is None and not (tmp_path / updater.NEW_NAME).exists()
