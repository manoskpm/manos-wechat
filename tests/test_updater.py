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
