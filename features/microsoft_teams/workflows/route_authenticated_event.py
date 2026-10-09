"""Route verified Microsoft Bot Framework activities to a generic topic."""

from __future__ import annotations

from typing import Any

from bifrost import UserError, context, events, integrations, workflow


TEAMS_INTEGRATION_NAME = "Microsoft Teams Bot"
ROUTED_EVENT_TOPIC = "microsoft_teams.activity_received"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _activity_tenant_id(activity: dict[str, Any]) -> str:
    channel_data = _as_dict(activity.get("channelData"))
    tenant = _as_dict(channel_data.get("tenant"))
    return str(
        tenant.get("id")
        or channel_data.get("tenantId")
        or _as_dict(activity.get("conversation")).get("tenantId")
        or ""
    ).strip()


def _verified_adapter_data() -> dict[str, Any]:
    """Read and validate the shape emitted by MicrosoftBotFrameworkAdapter.

    This workflow has no activity parameter. The webhook adapter validates the
    Bot Framework bearer token before the platform places its normalized data
    in ``context.event``; accepting a workflow argument here would bypass that
    boundary.
    """
    event = getattr(context, "event", None)
    data = _as_dict(getattr(event, "data", None))
    activity = _as_dict(data.get("activity"))
    activity_type = str(data.get("activity_type") or "").strip()
    service_url = str(data.get("service_url") or "").strip()
    channel_id = str(data.get("channel_id") or "").strip()
    tenant_id = str(data.get("tenant_id") or "").strip()
    sender = _as_dict(data.get("sender"))
    if (
        not activity
        or not activity_type
        or not service_url.startswith("https://")
        or channel_id != "msteams"
        or not tenant_id
        or not sender
    ):
        raise UserError("The event is not a complete Microsoft Bot Framework activity")
    if (
        str(activity.get("type") or "unknown") != activity_type
        or str(activity.get("serviceUrl") or "").strip() != service_url
        or str(activity.get("channelId") or "").strip() != channel_id
        or _activity_tenant_id(activity) != tenant_id
        or _as_dict(activity.get("from")) != sender
    ):
        raise UserError("The Microsoft Bot Framework activity does not match adapter data")
    return data


async def _scope_to_activity_tenant(activity: dict[str, Any]) -> str:
    """Resolve an authenticated Teams activity to exactly one Bifrost org."""
    tenant_id = _activity_tenant_id(activity)
    if not tenant_id:
        raise UserError("The Microsoft Teams activity did not identify its tenant")

    mappings = await integrations.list_mappings(
        TEAMS_INTEGRATION_NAME,
        scope="global",
    ) or []
    matches = [
        mapping
        for mapping in mappings
        if str(mapping.entity_id or "").strip().lower() == tenant_id.lower()
        and mapping.organization_id
    ]
    if not matches:
        raise UserError("This Microsoft Teams tenant is not configured in Bifrost")
    if len(matches) != 1:
        raise UserError("This Microsoft Teams tenant has ambiguous Bifrost mappings")

    organization_id = str(matches[0].organization_id)
    context.set_scope(organization_id)
    return organization_id


@workflow(
    name="route_authenticated_teams_event",
    description=(
        "Route a verified Microsoft Bot Framework activity to the "
        "microsoft_teams.activity_received topic in its mapped organization."
    ),
    category="Microsoft Teams",
)
async def route_authenticated_teams_event() -> dict[str, Any]:
    """Route an adapter-verified activity without interpreting its business meaning."""
    try:
        data = _verified_adapter_data()
        organization_id = await _scope_to_activity_tenant(_as_dict(data.get("activity")))
    except UserError as exc:
        message = str(exc)
        if message == "This Microsoft Teams tenant is not configured in Bifrost":
            return {"routed": False, "reason": "unknown_tenant"}
        if message == "This Microsoft Teams tenant has ambiguous Bifrost mappings":
            return {"routed": False, "reason": "ambiguous_tenant"}
        return {"routed": False, "reason": "invalid_adapter_event"}

    await events.emit(ROUTED_EVENT_TOPIC, data, scope=organization_id)
    return {
        "routed": True,
        "topic": ROUTED_EVENT_TOPIC,
        "organization_id": organization_id,
    }
