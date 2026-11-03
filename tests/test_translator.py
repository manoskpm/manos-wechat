import json
from types import SimpleNamespace

from app.config import DEFAULTS
from app.translator import Translator, build_request


def test_build_request_shape():
    req = build_request(cfg=DEFAULTS, user_instructions="회사명은 구름콩방", vendor="老王",
                        history=[{"side": "in", "zh": "你好", "ko": "안녕하세요"}],
                        direction="out", text="샘플 보내주세요", tone="firm")
    assert req["model"] == "claude-sonnet-5-5"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "구름콩방" in req["system"][0]["text"]
    content = req["messages"][0]["content"]
    assert "<message>\n샘플 보내주세요\n</message>" in content
    assert "[업체] 你好" in content
    assert "양보의 여지" in content


def test_run_parses_json():
    t = Translator.__new__(Translator)
    payload = {"korean": "안녕하세요", "nuance": "", "certainty": "none"}
    resp = SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=json.dumps(payload))])
    t.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: resp)))
    assert t.run({}) == payload


def test_partial_options_from_unfinished_answer():
    """AI가 아직 쓰는 중인 답에서도 완성된 후보만 꺼냄."""
    from app.translator import partial_options
    full = ('{"options": [{"label": "정중하게(추천)", "chinese": "老板您好", "back_translation": "사장님 안녕하세요"}, '
            '{"label": "짧게", "chinese": "老板好", "back_translation": "사장님"}], "note": ""}')
    assert partial_options(full[:20]) == []
    cut = full.index("}, ") + 1
    assert [o["chinese"] for o in partial_options(full[:cut])] == ["老板您好"]
    assert [o["chinese"] for o in partial_options(full[:cut + 30])] == ["老板您好"]
    assert [o["chinese"] for o in partial_options(full)] == ["老板您好", "老板好"]
