# Microsoft Teams workspace example

This reusable example provides a mapped Microsoft Teams Bot Framework transport,
four workflow entry points (`send`, `update`, `delete`, and `typing`), and an
authenticated inbound router. It is deliberately a transport example. It does
not include an agent, PSA/ticket behavior, conversation-history table, or any
other private application stack.

The [planned website guide](https://docs.gobifrost.com/guides/microsoft-teams)
will cover the same setup with screenshots when it is published.

## Tenant model

Each Bifrost customer organization gets exactly one `Microsoft Teams Bot`
IntegrationMapping. Its `entity_id` and mapping `tenant_id` are the customer's
Entra tenant ID. The integration's global defaults contain the shared Azure Bot
credentials and its `bot_tenant_id`, the bot application's home tenant.

Connector calls for sending, replacing, deleting, and typing always acquire a
token from `bot_tenant_id` (or the existing `botframework.com` default when it
is absent). Microsoft Graph calls use the mapped customer's `tenant_id`. Do not
put a customer tenant ID in `bot_tenant_id`, and do not put bot credentials in
individual mappings.

## Install with the CLI

Run these commands from this directory after authenticating a Bifrost CLI that
matches the target instance. The `files write` commands are explicit writes to
the target workspace; use `--create-only` only for paths that do not already
exist.

```bash
bifrost login --url https://<your-bifrost-url>
bifrost requirements install Markdown

bifrost files write modules/microsoft_teams_bot.py --from-file ../../modules/microsoft_teams_bot.py --create-only
bifrost files write features/microsoft_teams/workflows/messages.py --from-file workflows/messages.py --create-only
bifrost files write features/microsoft_teams/workflows/route_authenticated_event.py --from-file workflows/route_authenticated_event.py --create-only

bifrost workflows register --global --path features/microsoft_teams/workflows/messages.py --function-name send_teams_message
bifrost workflows register --global --path features/microsoft_teams/workflows/messages.py --function-name update_teams_message
bifrost workflows register --global --path features/microsoft_teams/workflows/messages.py --function-name delete_teams_message
bifrost workflows register --global --path features/microsoft_teams/workflows/messages.py --function-name send_teams_typing
bifrost workflows register --global --path features/microsoft_teams/workflows/route_authenticated_event.py --function-name route_authenticated_teams_event

bifrost integrations create --name "Microsoft Teams Bot" --entity-id tenant_id --entity-id-name "Customer Entra tenant" --config-schema @integration.schema.yaml
bifrost integrations get "Microsoft Teams Bot" --json
bifrost api PUT /api/integrations/<integration-id>/config @home-defaults.template.json
bifrost integrations add-mapping "Microsoft Teams Bot" --organization "<customer-org>" --entity-id "<customer-tenant-id>" --entity-name "<customer-name>" --config @customer-mapping.template.json
```

If the named integration already exists, compare its schema before using
`integrations update`; replacing a schema can remove saved configuration keys.
Set actual secrets only in the target Bifrost instance. The templates contain
placeholders and must not be committed after filling them.

Create a global Bot Framework event source, then subscribe the router. The
adapter itself validates the Microsoft bearer token and accepts only Teams
activities before `context.event` is populated.

```bash
bifrost events create-source --global --name "Microsoft Teams Bot Framework" --source-type webhook --adapter microsoft_bot_framework --webhook-config '{"app_id":"<azure-bot-client-id>"}'
bifrost events subscribe "Microsoft Teams Bot Framework" --workflow route_authenticated_teams_event
bifrost events get-source "Microsoft Teams Bot Framework"
```

Use the callback URL reported by `events get-source` as the Azure Bot messaging
endpoint. The router takes no caller-supplied activity argument. It validates
the normalized adapter payload, finds exactly one global mapping by tenant ID,
sets that customer scope, and emits `microsoft_teams.activity_received` with
the adapter's normalized event data. Subscribe customer-scoped workflows to
that topic for the business behavior you want. Unknown and ambiguous tenant
mappings emit nothing.

## Build and upload the Teams package

The package builder creates an upload-ready ZIP with a Teams 1.25 manifest,
the required 192px color and 32px outline PNG icons, and SSO metadata. The
package ID and Azure Bot/client ID are separate values. `webApplicationInfo.id`
uses the Azure Bot/client ID and its resource is `api://<bot-app-id>`.

```bash
python3 package/build_package.py \
  --output /tmp/microsoft-teams-bot.zip \
  --app-id <teams-package-guid> \
  --bot-app-id <azure-bot-client-id> \
  --name "<bot-display-name>" \
  --developer-name "<provider-name>" \
  --website-url https://<provider-domain>/support \
  --privacy-url https://<provider-domain>/privacy \
  --terms-url https://<provider-domain>/terms \
  --valid-domain <provider-domain>
```

Upload that ZIP to the intended Teams tenant catalog, then install it there.
The package declares no resource-specific consent. A 403 during a particular
tenant's installation needs investigation of that tenant's app catalog and
installation policy; this example does not assume that RSC is required or that
one live app ID applies everywhere.

## Operator check

Run one dry-run before a live message. It validates the selected target and
shows the generated activity without sending it:

```bash
bifrost run features/microsoft_teams/workflows/messages.py --workflow send_teams_message --params '{"target_type":"conversation","conversation_id":"<known-conversation-id>","message":"Teams transport check","dry_run":true}'
```

For user or channel sends, the configured customer Graph authority must permit
the documented Teams app-install and user lookup operations. Review the Azure
Bot, Graph, Teams catalog, and customer policy requirements for your own
tenant before enabling production sends.
