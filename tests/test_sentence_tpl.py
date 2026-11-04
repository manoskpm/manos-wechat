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
