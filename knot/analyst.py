"""Claude 판단 엔진 — 시황 브리핑 해석 & W12 채점.

오케스트레이터가 '정성 판단'이 필요할 때 호출하는 도구.
API 키가 없으면 dry-run(프롬프트 조립만) 으로 동작해 파이프라인을 검증할 수 있다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from . import prompts


@dataclass
class AnalystResult:
    ok: bool
    data: dict[str, Any] | None = None
    raw: str = ""
    error: str | None = None
    prompt_system: str = ""
    prompt_user: str = ""


class Analyst:
    def __init__(self, api_key: str | None, model: str = "claude-sonnet-5", max_tokens: int = 2000):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # --- 시황 브리핑 해석 ---
    def analyze_briefing(self, frameworks: str, portfolio: str, briefing: str,
                         date: str, dry_run: bool = False) -> AnalystResult:
        system, user = prompts.build_analyst_messages(frameworks, portfolio, briefing, date)
        return self._run(system, user, dry_run)

    # --- W12 채점 ---
    def score_w12(self, frameworks: str, ticker: str, name: str, context: str,
                  fundamentals: str, dry_run: bool = False) -> AnalystResult:
        system, user = prompts.build_w12_messages(frameworks, ticker, name, context, fundamentals)
        return self._run(system, user, dry_run)

    # --- 공통 실행 ---
    def _run(self, system: str, user: str, dry_run: bool) -> AnalystResult:
        if dry_run or not self.enabled:
            return AnalystResult(
                ok=False,
                error=None if dry_run else "ANTHROPIC_API_KEY 없음 — dry-run 으로 표시",
                prompt_system=system, prompt_user=user,
            )
        try:
            import anthropic
        except ImportError:
            return AnalystResult(ok=False, error="anthropic SDK 미설치 (pip install anthropic)",
                                 prompt_system=system, prompt_user=user)
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            resp = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            data = _extract_json(text)
            return AnalystResult(ok=data is not None, data=data, raw=text,
                                 error=None if data is not None else "JSON 파싱 실패",
                                 prompt_system=system, prompt_user=user)
        except Exception as e:
            return AnalystResult(ok=False, error=f"{type(e).__name__}: {e}",
                                 prompt_system=system, prompt_user=user)


def _extract_json(text: str) -> dict[str, Any] | None:
    """모델 출력에서 첫 JSON 객체를 안전하게 추출."""
    if not text:
        return None
    # 코드펜스 제거
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
