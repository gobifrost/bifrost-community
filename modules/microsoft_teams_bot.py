"""Reusable Microsoft Teams Bot Framework transport helpers.

The mapped integration holds one customer tenant per Bifrost organization. Its
``bot_tenant_id`` remains the home tenant for the bot application's Connector
token; Graph requests use the mapped customer's ``tenant_id``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any, Literal
from urllib.parse import quote

import httpx
import markdown
from bifrost import UserError, integrations


INTEGRATION_NAME = "Microsoft Teams Bot"
DEFAULT_SERVICE_URL = "https://smba.trafficmanager.net/amer/"
logger = logging.getLogger(__name__)

_MAX_RETRIES = 10
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Honor Retry-After, otherwise use bounded exponential backoff with jitter."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    backoff = min(_BASE_BACKOFF_SECONDS * (2**attempt), _MAX_BACKOFF_SECONDS)
    return backoff + random.uniform(0, backoff * 0.25)


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Retry transient Microsoft HTTP responses using the module policy."""
    for attempt in range(_MAX_RETRIES + 1):
        response = await client.request(method, url, **kwargs)
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt >= _MAX_RETRIES:
                return response
            delay = _retry_delay(response, attempt)
            logger.warning(
                "Microsoft %s %s -> %s, retrying in %.1fs (attempt %d/%d)",
                method,
                response.request.url.host,
                response.status_code,
                delay,
                attempt + 1,
                _MAX_RETRIES,
            )
            await asyncio.sleep(delay)
            continue
        return response
    raise RuntimeError("Microsoft request retry loop exited unexpectedly")


def _markdown_to_teams_html(text: str) -> str:
    """Render Markdown as Teams-supported XML/HTML text."""
    rendered = markdown.markdown(str(text), extensions=["nl2br"])
    rendered = re.sub(r"<br\s*/?>", "<br>", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"</p>\s*<p>", "<br><br>", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"</?p>", "", rendered, flags=re.IGNORECASE)
    return rendered.strip()


async def load_config() -> dict[str, Any]:
    """Load the Teams bot integration mapped to the executing organization."""
    integration = await integrations.get(INTEGRATION_NAME)
    if not integration:
        raise UserError(f"{INTEGRATION_NAME} integration is not configured")
    cfg = dict(integration.config or {})
    missing = [
        key
        for key in ("tenant_id", "client_id", "client_secret")
        if not str(cfg.get(key) or "").strip()
    ]
    if missing:
        raise UserError(
            f"{INTEGRATION_NAME} is missing required configuration: " + ", ".join(missing)
        )
    return cfg


async def _oauth_token(
    client: httpx.AsyncClient,
    cfg: dict[str, Any],
    scope: str,
    tenant_id: str | None = None,
) -> str:
    response = await _request_with_retry(
        client,
        "POST",
        "https://login.microsoftonline.com/"
        f"{tenant_id or cfg['tenant_id']}/oauth2/v2.0/token",
        data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "client_credentials",
            "scope": scope,
        },
    )
    if response.is_error:
        raise UserError(
            f"Microsoft authentication failed ({response.status_code}); "
            "check the Teams bot integration credentials"
        )
    token = str(response.json().get("access_token") or "")
    if not token:
        raise UserError("Microsoft authentication returned no access token")
    return token


async def _connector_token(client: httpx.AsyncClient, cfg: dict[str, Any]) -> str:
    """Get a Bot Connector token from the configured bot home tenant."""
    return await _oauth_token(
        client,
        cfg,
        "https://api.botframework.com/.default",
        tenant_id=str(cfg.get("bot_tenant_id") or "botframework.com"),
    )


def _service_url(value: str | None) -> str:
    service_url = str(value or DEFAULT_SERVICE_URL).strip().rstrip("/")
    if not service_url.startswith("https://"):
        raise UserError("service_url must be HTTPS")
    return service_url


async def _resolve_user_id(
    client: httpx.AsyncClient,
    graph_token: str,
    user: str,
) -> str:
    response = await _request_with_retry(
        client,
        "GET",
        f"https://graph.microsoft.com/v1.0/users/{quote(user, safe='')}",
        params={"$select": "id"},
        headers={"Authorization": f"Bearer {graph_token}"},
    )
    if response.status_code == 404:
        raise UserError(f"Microsoft Teams user was not found: {user}")
    if response.is_error:
        raise UserError(
            f"Microsoft Graph could not resolve the Teams user ({response.status_code})"
        )
    return str(response.json()["id"])


async def get_user_profile(user_id: str) -> dict[str, Any]:
    """Resolve a Teams/AAD sender through the mapped customer's Graph tenant."""
    value = str(user_id or "").strip()
    if not value:
        raise UserError("user_id is required")
    cfg = await load_config()
    async with httpx.AsyncClient(timeout=30.0) as client:
        graph_token = await _oauth_token(client, cfg, "https://graph.microsoft.com/.default")
        response = await _request_with_retry(
            client,
            "GET",
            f"https://graph.microsoft.com/v1.0/users/{quote(value, safe='')}",
            params={"$select": "id,displayName,mail,userPrincipalName"},
            headers={"Authorization": f"Bearer {graph_token}"},
        )
    if response.status_code == 404:
        raise UserError("The Teams sender was not found in Microsoft Graph")
    if response.is_error:
        raise UserError(
            f"Microsoft Graph could not resolve the Teams sender ({response.status_code})"
        )
    return dict(response.json())


async def _ensure_installed(
    client: httpx.AsyncClient,
    graph_token: str,
    teams_app_id: str,
    target_type: Literal["user", "channel"],
    target_id: str,
) -> None:
    if target_type == "user":
        url = (
            "https://graph.microsoft.com/v1.0/users/"
            f"{quote(target_id, safe='')}/teamwork/installedApps"
        )
    else:
        url = f"https://graph.microsoft.com/v1.0/teams/{quote(target_id, safe='')}/installedApps"
    headers = {"Authorization": f"Bearer {graph_token}"}

    async def find_installation_id() -> str:
        listed = await _request_with_retry(
            client,
            "GET",
            url,
            headers=headers,
            params={"$expand": "teamsApp"},
        )
        if listed.is_error:
            raise UserError(
                "Microsoft Teams could not inspect the bot installation "
                f"({listed.status_code})"
            )
        for item in list(listed.json().get("value") or []):
            app = item.get("teamsApp") or {}
            if str(app.get("id") or "") == teams_app_id:
                return str(item.get("id") or "")
        return ""

    if await find_installation_id():
        return

    response = await _request_with_retry(
        client,
        "POST",
        url,
        headers=headers,
        json={
            "teamsApp@odata.bind": (
                "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/" f"{teams_app_id}"
            ),
        },
    )
    if response.status_code == 409 and await find_installation_id():
        return
    if response.status_code not in {200, 201, 204}:
        raise UserError(
            "Microsoft Teams could not install the bot "
            f"({response.status_code}); confirm the Teams catalog app ID "
            "and tenant installation permissions"
        )


async def send_message(
    *,
    target_type: Literal["user", "channel", "conversation"],
    message: str,
    user: str | None = None,
    team_id: str | None = None,
    channel_id: str | None = None,
    conversation_id: str | None = None,
    service_url: str | None = None,
    reply_to_id: str | None = None,
    adaptive_card: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    text_format: Literal["plain", "markdown", "xml"] | None = None,
    entities: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send one Teams activity or validate the fully resolved send plan."""
    text = str(message or "").strip()
    if not text:
        raise UserError("message is required")
    if target_type not in {"user", "channel", "conversation"}:
        raise UserError("target_type must be user, channel, or conversation")

    cfg = await load_config()
    resolved_service_url = _service_url(service_url)
    resolved_text_format = text_format
    if resolved_text_format is None:
        text = _markdown_to_teams_html(text)
        resolved_text_format = "xml"

    activity: dict[str, Any] = {"type": "message"}
    resolved_attachments = list(attachments or [])
    if adaptive_card:
        resolved_attachments.append(
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": adaptive_card,
            }
        )
    if resolved_attachments:
        activity["attachments"] = resolved_attachments
    else:
        activity["text"] = text
    if summary:
        activity["summary"] = str(summary)
    elif resolved_attachments:
        activity["summary"] = text
    if resolved_text_format:
        activity["textFormat"] = resolved_text_format
    if entities:
        activity["entities"] = list(entities)
    if reply_to_id:
        activity["replyToId"] = reply_to_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        bot_token = await _connector_token(client, cfg)
        headers = {"Authorization": f"Bearer {bot_token}"}

        if target_type == "conversation":
            if not conversation_id:
                raise UserError("conversation_id is required for a conversation target")
            endpoint = f"{resolved_service_url}/v3/conversations/{quote(conversation_id, safe='')}/activities"
            request_body: dict[str, Any] = activity
        else:
            teams_app_id = str(cfg.get("teams_app_id") or "").strip()
            if not teams_app_id:
                raise UserError(
                    "The Teams catalog app ID must be added to the Microsoft Teams Bot integration"
                )
            graph_token = await _oauth_token(client, cfg, "https://graph.microsoft.com/.default")

            if target_type == "user":
                if not user:
                    raise UserError("user is required for a user target")
                resolved_user_id = await _resolve_user_id(client, graph_token, user)
                if not dry_run:
                    await _ensure_installed(
                        client, graph_token, teams_app_id, "user", resolved_user_id
                    )
                request_body = {
                    "bot": {
                        "id": f"28:{cfg['client_id']}",
                        "name": str(cfg.get("bot_name") or "Bifrost"),
                    },
                    "members": [{"id": resolved_user_id}],
                    "channelData": {"tenant": {"id": cfg["tenant_id"]}},
                    "tenantId": cfg["tenant_id"],
                    "isGroup": False,
                }
            else:
                team_id = str(team_id or cfg.get("default_team_id") or "").strip()
                channel_id = str(channel_id or cfg.get("default_channel_id") or "").strip()
                if not team_id or not channel_id:
                    raise UserError(
                        "team_id and channel_id are required for a channel target; "
                        "set them explicitly or configure organization defaults"
                    )
                if not dry_run:
                    await _ensure_installed(client, graph_token, teams_app_id, "channel", team_id)
                request_body = {
                    "activity": activity,
                    "bot": {
                        "id": f"28:{cfg['client_id']}",
                        "name": str(cfg.get("bot_name") or "Bifrost"),
                    },
                    "channelData": {
                        "teamsChannelId": channel_id,
                        "teamsTeamId": team_id,
                        "tenant": {"id": cfg["tenant_id"]},
                        "team": {"id": team_id},
                        "channel": {"id": channel_id},
                    },
                    "tenantId": cfg["tenant_id"],
                    "isGroup": True,
                }
            endpoint = f"{resolved_service_url}/v3/conversations"

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "target_type": target_type,
                "service_url": resolved_service_url,
                "credentials_valid": True,
                "request": request_body,
                "activity": activity,
            }

        response = await _request_with_retry(
            client, "POST", endpoint, headers=headers, json=request_body
        )
        if response.is_error:
            raise UserError(
                f"Microsoft Teams rejected the message ({response.status_code}): "
                f"{response.text[:500]}"
            )
        result = response.json() if response.content else {}
        if target_type == "conversation":
            returned_conversation_id = conversation_id
            activity_id = result.get("id")
            response_payload: dict[str, Any] = result
        elif target_type == "channel":
            returned_conversation_id = str(result.get("id") or "")
            if not returned_conversation_id:
                raise UserError("Microsoft Teams created no channel conversation ID")
            activity_id = result.get("activityId")
            if not activity_id:
                raise UserError("Microsoft Teams created no channel activity ID")
            response_payload = {"conversation": result, "activity": {"id": activity_id}}
        else:
            returned_conversation_id = str(result.get("id") or "")
            if not returned_conversation_id:
                raise UserError("Microsoft Teams created no conversation ID")
            activity_endpoint = (
                f"{resolved_service_url}/v3/conversations/"
                f"{quote(returned_conversation_id, safe='')}/activities"
            )
            activity_response = await _request_with_retry(
                client, "POST", activity_endpoint, headers=headers, json=activity
            )
            if activity_response.is_error:
                raise UserError(
                    "Microsoft Teams created the conversation but rejected the message "
                    f"({activity_response.status_code}): {activity_response.text[:500]}"
                )
            activity_result = activity_response.json() if activity_response.content else {}
            activity_id = activity_result.get("id")
            response_payload = {"conversation": result, "activity": activity_result}
        return {
            "success": True,
            "dry_run": False,
            "target_type": target_type,
            "service_url": resolved_service_url,
            "conversation_id": returned_conversation_id,
            "activity_id": activity_id,
            "reply_to_id": str(reply_to_id or "").strip(),
            "response": response_payload,
        }


async def _conversation_request(
    *,
    method: Literal["POST", "PUT", "DELETE"],
    conversation_id: str,
    service_url: str | None = None,
    activity_id: str | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one authenticated Bot Connector conversation endpoint."""
    if not str(conversation_id or "").strip():
        raise UserError("conversation_id is required")
    cfg = await load_config()
    resolved_service_url = _service_url(service_url)
    endpoint = f"{resolved_service_url}/v3/conversations/{quote(conversation_id, safe='')}/activities"
    if activity_id:
        endpoint += f"/{quote(str(activity_id), safe='')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        bot_token = await _connector_token(client, cfg)
        response = await _request_with_retry(
            client,
            method,
            endpoint,
            headers={"Authorization": f"Bearer {bot_token}"},
            json=body,
        )
        if response.is_error:
            raise UserError(
                f"Microsoft Teams rejected the activity ({response.status_code}): "
                f"{response.text[:500]}"
            )
        result = response.json() if response.content else {}
        return {
            "success": True,
            "conversation_id": conversation_id,
            "activity_id": result.get("id") or activity_id,
            "response": result,
        }


async def update_message(
    *,
    conversation_id: str,
    activity_id: str,
    message: str,
    service_url: str | None = None,
    adaptive_card: dict[str, Any] | None = None,
    summary: str | None = None,
    text_format: Literal["plain", "markdown", "xml"] | None = None,
) -> dict[str, Any]:
    """Replace one bot-authored Teams message or card."""
    text = str(message or "").strip()
    if not text and not adaptive_card:
        raise UserError("message is required when adaptive_card is absent")
    body: dict[str, Any] = {"type": "message"}
    if adaptive_card:
        body["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": adaptive_card,
            }
        ]
    else:
        resolved_text_format = text_format
        if resolved_text_format is None:
            text = _markdown_to_teams_html(text)
            resolved_text_format = "xml"
        body["text"] = text
        body["textFormat"] = resolved_text_format
    if summary:
        body["summary"] = str(summary)
    return await _conversation_request(
        method="PUT",
        conversation_id=conversation_id,
        activity_id=activity_id,
        service_url=service_url,
        body=body,
    )


async def delete_message(
    *, conversation_id: str, activity_id: str, service_url: str | None = None
) -> dict[str, Any]:
    """Delete one bot-authored Teams message."""
    return await _conversation_request(
        method="DELETE",
        conversation_id=conversation_id,
        activity_id=activity_id,
        service_url=service_url,
    )


async def send_typing(
    *, conversation_id: str, service_url: str | None = None
) -> dict[str, Any]:
    """Send a transient typing indicator to a Teams conversation."""
    return await _conversation_request(
        method="POST",
        conversation_id=conversation_id,
        service_url=service_url,
        body={"type": "typing"},
    )
