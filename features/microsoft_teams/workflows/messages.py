"""Workflow entry points for the reusable Teams transport."""

from __future__ import annotations

from typing import Any, Literal

from bifrost import workflow
from modules.microsoft_teams_bot import (
    delete_message,
    send_message,
    send_typing,
    update_message,
)


@workflow(
    name="send_teams_message",
    description="Send a Microsoft Teams bot message to a user, channel, or known conversation.",
    category="Microsoft Teams",
)
async def send_teams_message(
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
    return await send_message(
        target_type=target_type,
        message=message,
        user=user,
        team_id=team_id,
        channel_id=channel_id,
        conversation_id=conversation_id,
        service_url=service_url,
        reply_to_id=reply_to_id,
        adaptive_card=adaptive_card,
        attachments=attachments,
        summary=summary,
        text_format=text_format,
        entities=entities,
        dry_run=dry_run,
    )


@workflow(
    name="update_teams_message",
    description="Replace one bot-authored Microsoft Teams message or Adaptive Card.",
    category="Microsoft Teams",
)
async def update_teams_message(
    conversation_id: str,
    activity_id: str,
    message: str,
    service_url: str | None = None,
    adaptive_card: dict[str, Any] | None = None,
    summary: str | None = None,
    text_format: Literal["plain", "markdown", "xml"] | None = None,
) -> dict[str, Any]:
    return await update_message(
        conversation_id=conversation_id,
        activity_id=activity_id,
        message=message,
        service_url=service_url,
        adaptive_card=adaptive_card,
        summary=summary,
        text_format=text_format,
    )


@workflow(
    name="delete_teams_message",
    description="Delete one bot-authored Microsoft Teams message.",
    category="Microsoft Teams",
)
async def delete_teams_message(
    conversation_id: str,
    activity_id: str,
    service_url: str | None = None,
) -> dict[str, Any]:
    return await delete_message(
        conversation_id=conversation_id,
        activity_id=activity_id,
        service_url=service_url,
    )


@workflow(
    name="send_teams_typing",
    description="Send a transient Microsoft Teams typing indicator.",
    category="Microsoft Teams",
)
async def send_teams_typing(
    conversation_id: str,
    service_url: str | None = None,
) -> dict[str, Any]:
    return await send_typing(conversation_id=conversation_id, service_url=service_url)
