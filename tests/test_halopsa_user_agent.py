import asyncio
import sys
from types import ModuleType, SimpleNamespace

from modules import halopsa


def test_lazy_client_sets_a_user_agent_for_halo_requests(monkeypatch):
    async def get_integration(name):
        assert name == "HaloPSA"
        return SimpleNamespace(
            config={"base_url": "https://example.halopsa.com/api"},
            oauth=SimpleNamespace(access_token="test-token"),
        )

    monkeypatch.setitem(
        sys.modules,
        "bifrost",
        ModuleType("bifrost"),
    )
    sys.modules["bifrost"].integrations = SimpleNamespace(get=get_integration)

    client = asyncio.run(halopsa._LazyClient()._ensure_client())

    assert client.session.headers["User-Agent"] == "Bifrost/1.0 (+https://gobifrost.com)"
