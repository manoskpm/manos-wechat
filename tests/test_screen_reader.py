"""그림으로 그린 가짜 위챗 화면으로 화면 인식 규칙을 확인 (실제 대화 내용 없음)."""
from PIL import Image, ImageDraw

from app.chat_parser import Line
from app.screen_reader import (background_color, bubble_side_by_color, detect_header_bottom,
                               detect_input_top)

W, H, LEFT = 1000, 800, 360
BG = (245, 245, 245)


def fake_wechat():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, LEFT - 1, H], fill=(230, 230, 230))          # 대화방 목록
    d.line([(LEFT, 98), (W, 98)], fill=(225, 225, 225), width=1)      # 제목 아래 선
    d.rectangle([LEFT + 10, 640, W - 10, 790], outline=(215, 215, 215), width=2, fill=(255, 255, 255))  # 입력창
    # 업체 말풍선 (흰색) 2줄
    d.rectangle([LEFT + 70, 150, LEFT + 400, 215], fill=(255, 255, 255))
    d.rectangle([LEFT + 84, 160, LEFT + 380, 180], fill=(30, 30, 30))
    d.rectangle([LEFT + 84, 186, LEFT + 200, 206], fill=(30, 30, 30))
    # 내 말풍선 (초록)
    d.rectangle([W - 420, 260, W - 70, 300], fill=(149, 236, 105))
    d.rectangle([W - 406, 270, W - 90, 290], fill=(30, 30, 30))
    # 사진 (알록달록) 안의 글자
    for i in range(0, 200, 10):
        d.rectangle([LEFT + 70 + i, 350, LEFT + 80 + i, 550], fill=(40 + i, 120, 200 - i // 2))
    d.rectangle([LEFT + 150, 420, LEFT + 230, 440], fill=(255, 255, 255))
    return img


def test_dividers_found():
    img = fake_wechat()
    assert detect_header_bottom(img, LEFT) == 98
    assert 638 <= detect_input_top(img, LEFT) <= 642


def test_bubble_sides_and_photo():
    img = fake_wechat()
    bg = background_color(img, LEFT, 98)
    assert bg == BG
    side = lambda x0, y0, x1, y1: bubble_side_by_color(img, Line(x0, y0, x1, y1, "x"), LEFT, bg)
    assert side(84, 160, 380, 180) == "in"
    assert side(84, 186, 200, 206) == "in"            # 말풍선 둘째 줄
    assert side(W - 406 - LEFT, 270, W - 90 - LEFT, 290) == "out"
    assert side(150, 420, 230, 440) == "photo"        # 사진 속 글자


def test_title_signature_separates_rooms_with_same_icons():
    """위챗 창 버튼·아이콘은 같고 이름만 다른 두 방 → 다른 방, 같은 방 → 같은 방."""
    from PIL import ImageFont

    from app.screen_reader import same_title, signature_distance, title_signature
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 18)
    except OSError:
        font = ImageFont.load_default()

    def title(name):
        img = Image.new("RGB", (450, 58), (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.text((30, 18), "<", fill=(30, 30, 30), font=font)
        d.text((60, 18), name, fill=(25, 25, 25), font=font)
        for x in (330, 370, 410):  # 오른쪽 아이콘들
            d.ellipse([x, 20, x + 16, 36], outline=(40, 40, 40), width=2)
        return title_signature(img)

    a, b = title("나희씨 중국 메인직원"), title("A汇星盛通中韩双向")
    assert same_title(a, title("나희씨 중국 메인직원"))
    assert not same_title(a, b) and signature_distance(a, b) > 30


def test_estimate_shift_follows_scroll():
    """스크롤한 만큼(픽셀) 정확히 재고, 다른 화면이면 모른다고 함."""
    import numpy as np
    from PIL import Image, ImageDraw
    from app.screen_reader import chat_profile, estimate_shift
    rnd = np.random.RandomState(0)
    base = Image.new("RGB", (500, 1200), (250, 250, 250))
    d = ImageDraw.Draw(base)
    for y in range(20, 1180, 70):           # 말풍선처럼 생긴 네모들
        x = int(rnd.randint(30, 200))
        d.rectangle([x, y, x + int(rnd.randint(60, 250)), y + int(rnd.randint(20, 50))],
                    fill=tuple(int(v) for v in rnd.randint(150, 240, 3)))
    arr = np.asarray(base)
    box = (0, 100, 500, 1100)
    p0 = chat_profile(base, box)
    down = arr.copy(); down[220:1100] = arr[100:980]
    assert estimate_shift(p0, chat_profile(Image.fromarray(down), box)) == 120
    up = arr.copy(); up[100:1023] = arr[177:1100]
    assert estimate_shift(p0, chat_profile(Image.fromarray(up), box)) == -77
    other = Image.fromarray(np.full_like(arr, 250)); ImageDraw.Draw(other).rectangle([10, 300, 400, 900], fill=(30, 30, 30))
    assert estimate_shift(p0, chat_profile(other, box)) is None
