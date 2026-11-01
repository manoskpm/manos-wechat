"""윈도우 빌드 환경에서 윈도우 글자 인식(PowerShell) 경로가 실제로 동작하는지 확인 (영어로 시험)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont

from app.korean_ocr import read_text  # noqa: E402

img = Image.new("RGB", (420, 90), "white")
try:
    font = ImageFont.truetype("arial.ttf", 48)
except OSError:
    font = ImageFont.load_default()
ImageDraw.Draw(img).text((10, 15), "HELLO MANOS", fill="black", font=font)
text = read_text(img, lang="en-US")
print("windows ocr result:", repr(text))
assert text and "HELLO" in text.upper(), "윈도우 글자 인식 실패"
