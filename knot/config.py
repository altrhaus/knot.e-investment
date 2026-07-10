"""설정 로드 — .env(키) + config/settings.json(런타임 설정)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv 미설치여도 환경변수는 동작
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

ROOT = Path(__file__).resolve().parent.parent


def _load_settings() -> dict[str, Any]:
    base = ROOT / "config" / "settings.json"
    local = ROOT / "config" / "settings.local.json"
    data: dict[str, Any] = {}
    if base.exists():
        data.update(json.loads(base.read_text(encoding="utf-8")))
    if local.exists():  # 로컬 오버라이드
        data.update(json.loads(local.read_text(encoding="utf-8")))
    return data


@dataclass
class Config:
    """런타임 설정 + 키 컨테이너."""
    anthropic_api_key: str | None = None
    model: str = "claude-sonnet-5"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    market_data_provider: str = "yfinance"
    finnhub_api_key: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    root: Path = ROOT

    # --- 경로 헬퍼 ---
    def path(self, key: str, default: str) -> Path:
        rel = self.settings.get("paths", {}).get(key, default)
        return self.root / rel

    @property
    def frameworks_dir(self) -> Path:
        return self.path("frameworks_dir", "frameworks")

    @property
    def holdings_file(self) -> Path:
        return self.path("holdings", "data/holdings.json")

    @property
    def watchlist_file(self) -> Path:
        return self.path("watchlist", "data/watchlist.json")

    @property
    def has_claude(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_config() -> Config:
    """`.env` 와 settings.json 을 읽어 Config 를 만든다."""
    load_dotenv(ROOT / ".env")
    settings = _load_settings()
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        # 우선순위: 환경변수 KNOTE_MODEL > settings.json > 기본값
        model=os.getenv("KNOTE_MODEL") or settings.get("model") or "claude-sonnet-5",
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        market_data_provider=os.getenv("MARKET_DATA_PROVIDER") or "yfinance",
        finnhub_api_key=os.getenv("FINNHUB_API_KEY") or None,
        settings=settings,
    )
