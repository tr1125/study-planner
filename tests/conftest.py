"""Offline test fixtures: a scripted fake Messages client and a fake holiday API. No API key needed."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from anthropic.types import Message

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TODAY = "2026-11-22"

HEBCAL_PAYLOAD = {
    "items": [
        {"title": "Chanukah: 1 Candle", "date": "2026-12-04", "category": "holiday", "subcat": "major", "memo": "long text"},
        {"title": "Chanukah: 2 Candles", "date": "2026-12-05", "category": "holiday", "subcat": "major"},
        {"title": "Rosh Chodesh Tevet", "date": "2026-12-10", "category": "roshchodesh"},
        {"title": "Chanukah: 3 Candles", "date": "2026-12-06", "category": "holiday", "subcat": "major"},
        {"title": "Parashat Vayeshev", "date": "2026-12-05", "category": "parashat"},
    ]
}


def fake_fetch(url: str) -> dict:
    fake_fetch.urls.append(url)
    return HEBCAL_PAYLOAD


fake_fetch.urls = []


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def tool_use(id_: str, name: str, input_: dict) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


def thinking(sig: str = "sig") -> dict:
    return {"type": "thinking", "thinking": "", "signature": sig}


def reply(content: list[dict], stop_reason: str = "end_turn", usage: dict | None = None) -> Message:
    usage = usage or {"input_tokens": 100, "output_tokens": 20,
                      "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50}
    return Message.model_validate({
        "id": "msg_x", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None, "usage": usage,
    })


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns scripted responses, records every request."""

    def __init__(self, script: list[Message]):
        self.script = list(script)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs) -> Message:
        self.requests.append(copy.deepcopy(kwargs))
        if not self.script:
            raise AssertionError("FakeClient: no scripted response left")
        return self.script.pop(0)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"
