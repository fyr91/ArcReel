from __future__ import annotations

from copy import deepcopy

import pytest

from lib.agent_session_store.image_filter import IMAGE_OMITTED_TEXT, TextOnlySessionStore, omit_images_for_text_model

pytestmark = pytest.mark.unit


def test_omit_images_replaces_nested_tool_result_without_mutating_source() -> None:
    entries = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "data": "paid-bytes"}},
                            {"type": "text", "text": "metadata"},
                        ],
                    }
                ]
            },
        }
    ]
    original = deepcopy(entries)

    filtered = omit_images_for_text_model(entries)

    assert entries == original
    assert filtered is not None
    blocks = filtered[0]["message"]["content"][0]["content"]
    assert blocks == [
        {"type": "text", "text": IMAGE_OMITTED_TEXT},
        {"type": "text", "text": "metadata"},
    ]


class _Store:
    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries
        self.appended: list[dict] = []

    async def load(self, _key: dict) -> list[dict]:
        return self.entries

    async def append(self, _key: dict, entries: list[dict]) -> None:
        self.appended.extend(entries)


async def test_text_only_store_filters_load_but_keeps_append_lossless() -> None:
    image_entry = {"type": "user", "message": {"content": [{"type": "image", "source": {"data": "x"}}]}}
    backing = _Store([image_entry])
    store = TextOnlySessionStore(backing)

    loaded = await store.load({"session_id": "s"})
    await store.append({"session_id": "s"}, [image_entry])

    assert loaded is not None
    assert loaded[0]["message"]["content"] == [{"type": "text", "text": IMAGE_OMITTED_TEXT}]
    assert backing.appended == [image_entry]
