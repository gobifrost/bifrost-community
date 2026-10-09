"""Focused contracts for the reusable Microsoft Teams workspace example."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]


class FakeUserError(Exception):
    pass


class FakeContext:
    event = None
    scope = None

    @classmethod
    def set_scope(cls, organization_id: str) -> None:
        cls.scope = organization_id


class FakeIntegrations:
    mappings = []

    @classmethod
    async def get(cls, _name: str):
        return None

    @classmethod
    async def list_mappings(cls, _name: str, *, scope: str):
        assert scope == "global"
        return cls.mappings


class FakeEvents:
    emit = AsyncMock()


def load_example(relative_path: str, module_name: str):
    """Load a workspace module against a small SDK boundary double."""
    sdk = types.ModuleType("bifrost")
    sdk.UserError = FakeUserError
    sdk.context = FakeContext
    sdk.events = FakeEvents
    sdk.integrations = FakeIntegrations
    sdk.workflow = lambda function=None, **_kwargs: function or (lambda item: item)
    sys.modules["bifrost"] = sdk
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class MicrosoftTeamsTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.transport = load_example(
            "modules/microsoft_teams_bot.py", "workspace_teams_transport"
        )
        self.config = {
            "tenant_id": "customer-tenant",
            "bot_tenant_id": "bot-home-tenant",
            "client_id": "client-id",
            "client_secret": "secret",
        }
        self.transport.load_config = AsyncMock(return_value=self.config)

    async def test_connector_authority_is_shared_by_all_activity_consumers(self) -> None:
        token_tenants: list[str | None] = []

        async def oauth(_client, _cfg, _scope, tenant_id=None):
            token_tenants.append(tenant_id)
            return "bot-token"

        class Response:
            is_error = False
            content = b'{}'

            def json(self):
                return {}

        self.transport._oauth_token = oauth
        self.transport._request_with_retry = AsyncMock(return_value=Response())

        await self.transport.send_message(
            target_type="conversation",
            conversation_id="conversation-id",
            message="Hello",
            dry_run=True,
        )
        await self.transport.update_message(
            conversation_id="conversation-id", activity_id="activity-id", message="Hello"
        )
        await self.transport.delete_message(
            conversation_id="conversation-id", activity_id="activity-id"
        )
        await self.transport.send_typing(conversation_id="conversation-id")

        self.assertEqual(token_tenants, ["bot-home-tenant"] * 4)

    async def test_graph_uses_customer_authority_and_installation_payload_is_minimal(self) -> None:
        class Response:
            is_error = False
            status_code = 200
            content = b'{"access_token": "graph-token"}'

            def json(self):
                return {"access_token": "graph-token"}

        requests: list[tuple[str, str]] = []

        async def graph_request(_client, method, url, **_kwargs):
            requests.append((method, url))
            response = Response()
            if method == "GET":
                response.content = b'{"id": "user-id"}'
                response.json = lambda: {"id": "user-id"}
            return response

        self.transport._request_with_retry = graph_request
        await self.transport.get_user_profile("user@example.test")
        self.assertEqual(
            requests[0],
            (
                "POST",
                "https://login.microsoftonline.com/customer-tenant/oauth2/v2.0/token",
            ),
        )

        listed = Response()
        listed.content = b'{"value": []}'
        listed.json = lambda: {"value": []}
        created = Response()
        created.status_code = 201
        self.transport._request_with_retry = AsyncMock(side_effect=[listed, created])
        await self.transport._ensure_installed(
            object(), "graph-token", "catalog-app-id", "user", "user-id"
        )
        install_request = self.transport._request_with_retry.await_args_list[1].kwargs["json"]
        self.assertEqual(
            install_request,
            {
                "teamsApp@odata.bind": (
                    "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/catalog-app-id"
                )
            },
        )


class AuthenticatedTeamsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeContext.event = None
        FakeContext.scope = None
        FakeEvents.emit.reset_mock()
        FakeIntegrations.mappings = []
        self.router = load_example(
            "features/microsoft_teams/workflows/route_authenticated_event.py",
            "workspace_teams_router",
        )

    async def test_routes_only_verified_adapter_event_to_the_generic_topic(self) -> None:
        FakeIntegrations.mappings = [
            types.SimpleNamespace(entity_id="tenant-id", organization_id="org-id")
        ]
        FakeContext.event = types.SimpleNamespace(
            data={
                "activity": {
                    "type": "message",
                    "channelId": "msteams",
                    "serviceUrl": "https://smba.trafficmanager.net/amer/",
                    "channelData": {"tenant": {"id": "tenant-id"}},
                    "conversation": {"id": "conversation-id"},
                    "from": {"id": "user-id"},
                },
                "activity_type": "message",
                "activity_id": "activity-id",
                "service_url": "https://smba.trafficmanager.net/amer/",
                "channel_id": "msteams",
                "tenant_id": "tenant-id",
                "conversation_id": "conversation-id",
                "sender": {"id": "user-id"},
            }
        )

        result = await self.router.route_authenticated_teams_event()

        self.assertEqual(result["routed"], True)
        FakeEvents.emit.assert_awaited_once_with(
            "microsoft_teams.activity_received",
            FakeContext.event.data,
            scope="org-id",
        )

    async def test_unknown_or_ambiguous_tenant_does_not_invoke_a_consumer(self) -> None:
        FakeContext.event = types.SimpleNamespace(
            data={
                "activity": {
                    "type": "message",
                    "channelId": "msteams",
                    "serviceUrl": "https://smba.trafficmanager.net/amer/",
                    "channelData": {"tenant": {"id": "tenant-id"}},
                    "from": {"id": "user-id"},
                },
                "activity_type": "message",
                "service_url": "https://smba.trafficmanager.net/amer/",
                "channel_id": "msteams",
                "tenant_id": "tenant-id",
                "sender": {"id": "user-id"},
            }
        )
        for mappings, reason in (
            ([], "unknown_tenant"),
            (
                [
                    types.SimpleNamespace(entity_id="tenant-id", organization_id="first"),
                    types.SimpleNamespace(entity_id="tenant-id", organization_id="second"),
                ],
                "ambiguous_tenant",
            ),
        ):
            with self.subTest(reason=reason):
                FakeIntegrations.mappings = mappings
                result = await self.router.route_authenticated_teams_event()
                self.assertEqual(result, {"routed": False, "reason": reason})
        FakeEvents.emit.assert_not_awaited()


class TeamsPackageTests(unittest.TestCase):
    def test_builds_a_1_25_package_with_sso_and_no_rsc(self) -> None:
        builder = load_example(
            "features/microsoft_teams/package/build_package.py", "workspace_teams_package"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "teams.zip"
            builder.build_package(
                output=output,
                app_id="11111111-1111-1111-1111-111111111111",
                bot_app_id="22222222-2222-2222-2222-222222222222",
                name="Example Bot",
                developer_name="Example Provider",
                website_url="https://provider.example.test/help",
                privacy_url="https://provider.example.test/privacy",
                terms_url="https://provider.example.test/terms",
                valid_domains=["provider.example.test"],
            )
            with zipfile.ZipFile(output) as package:
                self.assertEqual(set(package.namelist()), {"manifest.json", "color.png", "outline.png"})
                manifest = json.loads(package.read("manifest.json"))
                self.assertEqual(package.read("color.png")[16:24], b"\x00\x00\x00\xc0\x00\x00\x00\xc0")
                self.assertEqual(package.read("outline.png")[16:24], b"\x00\x00\x00 \x00\x00\x00 ")
            self.assertEqual(manifest["manifestVersion"], "1.25")
            self.assertEqual(manifest["bots"][0]["botId"], "22222222-2222-2222-2222-222222222222")
            self.assertEqual(
                manifest["webApplicationInfo"],
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "resource": "api://22222222-2222-2222-2222-222222222222",
                },
            )
            self.assertNotIn("authorization", manifest)
            self.assertNotIn("resourceSpecific", manifest)


class TeamsOperatorFixturesTests(unittest.TestCase):
    def test_catalog_app_id_is_customer_mapping_configuration(self) -> None:
        home_defaults = json.loads(
            (ROOT / "features/microsoft_teams/home-defaults.template.json").read_text()
        )
        customer_mapping = json.loads(
            (ROOT / "features/microsoft_teams/customer-mapping.template.json").read_text()
        )

        self.assertNotIn("teams_app_id", home_defaults["config"])
        self.assertEqual(customer_mapping["teams_app_id"], "<teams-catalog-app-id>")

    def test_readme_links_the_public_shared_bot_guide(self) -> None:
        readme = (ROOT / "features/microsoft_teams/README.md").read_text()

        self.assertIn(
            "https://gobifrost.com/docs/how-to-guides/integrations/shared-teams-bot/",
            readme,
        )
        self.assertNotIn("https://docs.gobifrost.com/guides/microsoft-teams", readme)


if __name__ == "__main__":
    unittest.main()
