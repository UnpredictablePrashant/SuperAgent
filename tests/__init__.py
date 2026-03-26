# Test package marker.
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


try:
    import langchain_openai as _langchain_openai  # noqa: F401
except ModuleNotFoundError:
    fake_module = ModuleType("langchain_openai")

    class _FakeChatOpenAI:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def invoke(self, *args, **kwargs):
            return SimpleNamespace(content="")

    fake_module.ChatOpenAI = _FakeChatOpenAI
    sys.modules["langchain_openai"] = fake_module
