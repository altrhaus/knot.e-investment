"""알림 도구 — 텔레그램 (Phase 3). 미설정이면 조용히 no-op."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NotifyResult:
    ok: bool
    detail: str = ""


class Notifier:
    def __init__(self, bot_token: str | None, chat_id: str | None):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, text: str) -> NotifyResult:
        if not self.enabled:
            return NotifyResult(ok=False, detail="텔레그램 미설정 (.env TELEGRAM_* )")
        try:
            import requests
        except ImportError:
            return NotifyResult(ok=False, detail="requests 미설치")
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            r = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            if r.status_code == 200:
                return NotifyResult(ok=True, detail="sent")
            return NotifyResult(ok=False, detail=f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            return NotifyResult(ok=False, detail=f"{type(e).__name__}: {e}")
