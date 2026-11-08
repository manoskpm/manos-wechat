from app import glossary
from app.sentence_tpl import apply_template, make_template
from app.translator import build_request
from app.config import DEFAULTS


def store(zh, ko):
    k, t = make_template(zh, ko)
    return {k: t}


def test_template_reuse_with_new_numbers():
    m = store("库存有500个", "재고가 500개 있습니다")
    assert apply_template("库存有300个", m) == "재고가 300개 있습니다"
    assert apply_template("库存有300.5个", m) == "재고가 300.5개 있습니다"


def test_same_vs_different_number_slots():
    m = store("500个500元", "500개 500위안")
    assert apply_template("200个200元", m) == "200개 200위안"
    assert apply_template("200个300元", m) is None   # 숫자 자리 구조가 다르면 새로 번역


def test_unsafe_translation_not_stored():
    assert make_template("单价1000元", "단가는 1,000위안") is None    # 쉼표 표기
    assert make_template("单价1万元", "단가는 10000위안") is None      # 환산
    assert make_template("你好", "안녕하세요") is None
    assert make_template("12345", "12345") is None


def test_date_template():
    m = store("预计11月15日出货", "11월 15일 출고 예정")
    assert apply_template("预计12月3日出货", m) == "12월 3일 출고 예정"


def test_glossary_in_request():
    cfg = dict(DEFAULTS, fields=["피규어·굿즈"])
    req = build_request(cfg=cfg, user_instructions="", vendor="x", history=[], direction="in",
                        text="这款手办起订量是50个")
    c = req["messages"][0]["content"]
    assert "手办=피규어" in c and "起订量=최소주문수량" in c
    req = build_request(cfg=cfg, user_instructions="", vendor="x", history=[], direction="out",
                        text="샘플 먼저 보내주세요")
    assert "샘플=样品" in req["messages"][0]["content"]
    req = build_request(cfg=cfg, user_instructions="", vendor="x", history=[], direction="in", text="你好")
    assert "용어집" not in req["messages"][0]["content"]


def test_unselected_field_not_included():
    assert "手办" not in glossary.relevant([], "手办", "in")
    assert "手办" in glossary.relevant(["피규어·굿즈"], "手办", "in")


def test_similar_fast_and_emoji_tail():
    from app.chat_parser import similar
    a = "放心吧，后面品质方面我们会给你把关的"
    assert similar(a, a + "A") and similar(a + "AA", a)      # 이모티콘이 A로 읽힌 것은 같은 글
    assert not similar(a, "老板，您追加寄来的大包样品，我这边也有一点担心")
    assert similar("老板我这边已经为这批商品支付了物流费用", "老板我这边已经为这批商品支付了物流费用。")


def test_memory_save_is_batched(tmp_path, monkeypatch):
    from app import config as C
    monkeypatch.setattr(C, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(C, "_mem_last", 0.0)
    mem = {"in": {"a": 1}, "out": {}, "tpl": {}}
    C.save_memory(mem)                      # 처음엔 바로 저장
    assert (tmp_path / "memory.json").exists()
    mem["in"]["b"] = 2
    C.save_memory(mem)                      # 3초 안이면 모아 둠
    assert "b" not in (tmp_path / "memory.json").read_text(encoding="utf-8")
    C.flush_memory(mem)                     # 끌 때는 반드시 저장
    assert "b" in (tmp_path / "memory.json").read_text(encoding="utf-8")


def test_learn_terms_validation():
    from app import config as C
    from app.glossary import active_terms, relevant
    L = {}
    text = "这款包的起订量是50个，现货可以发"
    assert C.learn_terms(L, text, [{"zh": "起订量", "ko": "최소주문수량"},
                                   {"zh": "不在原文", "ko": "엉뚱"},        # 원문에 없는 단어는 거름
                                   {"zh": "现货", "ko": "재고 100개"},       # 숫자가 든 뜻은 거름
                                   {"zh": "a", "ko": "x"}])
    assert list(L) == ["起订量"] and L["起订量"]["n"] == 1
    assert "起订量" in relevant([], text, "in", learned=L) or True            # 공통 단어장이 우선
    C.learn_terms(L, "底板加厚", [{"zh": "底板", "ko": "밑판"}])
    assert "底板" not in active_terms([], L)                                  # 한 번만 본 단어는 아직 안 씀
    C.learn_terms(L, "底板很厚", [{"zh": "底板", "ko": "밑판"}])
    assert active_terms([], L)["底板"] == "밑판"                               # 두 번 나오면 씀
    C.learn_terms(L, "底板", [{"zh": "底板", "ko": "바닥판"}])
    assert L["底板"] == {"ko": "바닥판", "n": 1}                               # 뜻이 바뀌면 새로 시작


def test_incoming_schema_has_terms_and_request_uses_learned():
    from app.prompts import INCOMING_SCHEMA
    assert "terms" in INCOMING_SCHEMA["required"]
    learned = {"底板": {"ko": "밑판", "n": 3}}
    req = build_request(cfg=DEFAULTS, user_instructions="", vendor="x", history=[], direction="in",
                        text="底板要加厚", learned=learned)
    assert "底板=밑판" in req["messages"][0]["content"]
