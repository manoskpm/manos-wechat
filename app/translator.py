"""Claude API로 번역하는 부분."""
from __future__ import annotations

import base64
import json

import anthropic

from .prompts import INCOMING_SCHEMA, OUTGOING_SCHEMA, SYSTEM_PROMPT, TONES

# 안전 분류기가 요청을 거절하면 서버가 알아서 다른 모델로 다시 처리하게 하는 기능
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class TranslateError(Exception):
    """사용자에게 그대로 보여줄 한국어 오류 메시지."""


def format_history(history: list[dict], limit: int) -> str:
    lines = []
    for h in history[-limit:]:
        if h.get("side") == "in":
            lines.append(f"[업체] {h.get('zh', '')}  (번역: {h.get('ko', '')})")
        else:
            lines.append(f"[대표] {h.get('zh', '')}  (원래 한국어: {h.get('ko', '')})")
    return "\n".join(lines) if lines else "(이전 대화 없음)"


def build_request(*, cfg: dict, user_instructions: str, vendor: str, history: list[dict],
                  direction: str, text: str, tone: str = "polite") -> dict:
    system = SYSTEM_PROMPT
    if user_instructions.strip():
        system += "\n## 대표의 추가 지시 (우선 적용)\n" + user_instructions.strip() + "\n"

    convo = format_history(history, cfg.get("history_for_prompt", 12))
    if direction == "in":
        task = (
            "작업: incoming. 아래 업체 메시지를 한국어로 옮기고 속뜻을 판단해.\n"
            f"<message>\n{text}\n</message>"
        )
        schema = INCOMING_SCHEMA
    else:
        tone_desc = TONES.get(tone, TONES["polite"])[1]
        task = (
            f"작업: outgoing. 말투: {tone_desc}\n"
            "아래 대표의 한국어를 업체에 보낼 중국어로 옮겨.\n"
            f"<message>\n{text}\n</message>"
        )
        schema = OUTGOING_SCHEMA

    user_content = f"거래처: {vendor or '(알 수 없음)'}\n\n최근 대화:\n{convo}\n\n{task}"
    return {
        "model": cfg.get("model", "claude-sonnet-5-5"),
        "max_tokens": 4000,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_content}],
        "output_config": {
            "effort": cfg.get("effort", "low"),
            "format": {"type": "json_schema", "schema": schema},
        },
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


class Translator:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)

    def run(self, request: dict) -> dict:
        try:
            resp = self.client.beta.messages.create(**request)
        except anthropic.AuthenticationError as e:
            raise TranslateError("API 키가 올바르지 않습니다. 설정에서 키를 확인해 주세요.") from e
        except anthropic.PermissionDeniedError as e:
            raise TranslateError("API 사용 권한이 없습니다. 결제 정보나 사용 한도를 확인해 주세요.") from e
        except anthropic.RateLimitError as e:
            raise TranslateError("요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.") from e
        except anthropic.APIStatusError as e:
            raise TranslateError(f"API 오류 ({e.status_code}). 잠시 후 다시 시도해 주세요.") from e
        except anthropic.APIConnectionError as e:
            raise TranslateError("인터넷 연결을 확인해 주세요.") from e

        if resp.stop_reason == "refusal":
            raise TranslateError("이 메시지는 AI가 처리를 거절했습니다. 표현을 바꿔 다시 시도해 주세요.")
        if resp.stop_reason == "max_tokens":
            raise TranslateError("메시지가 너무 깁니다. 나눠서 번역해 주세요.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except ValueError as e:
            raise TranslateError("번역 결과를 읽지 못했습니다. 다시 시도해 주세요.") from e


TITLE_PROMPT = ("이 그림은 위챗(WeChat) 대화방 맨 위의 제목 줄입니다. 대화방(상대방) 이름만 그대로 적어 주세요. "
                "설명이나 따옴표 없이 이름만 씁니다. 이름이 보이지 않으면 아무것도 쓰지 마세요.")


def build_title_request(cfg: dict, png: bytes) -> dict:
    """대화방 제목 줄 그림에서 이름을 읽는 요청 (윈도우 글자 인식이 실패할 때만, 대화방마다 한 번)."""
    return {
        "model": cfg.get("model", "claude-sonnet-5-5"),
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(png).decode("ascii")}},
            {"type": "text", "text": TITLE_PROMPT},
        ]}],
        "output_config": {"effort": "low"},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def read_title(translator: "Translator", cfg: dict, png: bytes) -> str:
    resp = translator.client.beta.messages.create(**build_title_request(cfg, png))
    if resp.stop_reason == "refusal":
        return ""
    text = next((b.text for b in resp.content if b.type == "text"), "").strip().strip('"\'「」')
    return text if 2 <= len(text.replace(" ", "")) <= 40 and "\n" not in text else ""
