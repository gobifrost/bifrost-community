# Bifrost Community

Community resources for [Bifrost](https://github.com/gobifrost/bifrost): a solutions index and workspace examples for MSPs.

## Solutions

Solutions package Bifrost apps, workflows, agents, and related resources for installation in your own instance. Each solution lives in its author's repository, with its own releases, setup instructions, and issue tracker. This README is the shared index.

### Maintained by gobifrost

| Solution | Description | Setup |
|----------|-------------|-------|
| [Bifrost Design System](https://github.com/gobifrost/design-system) | Shared design tokens, React components, and a Bifrost catalog app. | [README](https://github.com/gobifrost/design-system#readme) |
| [Bifrost DMARC](https://github.com/gobifrost/bifrost-dmarc) | Aggregate reporting, email investigation, and guarded DMARC/SPF changes through Cloudflare. | [Install, integrations, and access](https://github.com/gobifrost/bifrost-dmarc#install-and-connect) |

Bifrost GRC and Bifrost Docs are planned additions. Their repositories are currently private; [publication review](https://github.com/gobifrost/bifrost-community/issues/2) is tracked before listing them for installation.

### Community-maintained solutions

Have a solution to share? Keep it in your own public repository and [submit a pull request](https://github.com/gobifrost/bifrost-community/compare) to add a link here.

| Solution | Description | Maintainer | Setup |
|----------|-------------|------------|-------|
| [Halo SQL Studio](https://github.com/jackmusick/HaloSqlStudio) | Explore HaloPSA reporting tables, run queries, and manage reports through a configured Halo connection. [v0.1.3 source release](https://github.com/jackmusick/HaloSqlStudio/releases/tag/v0.1.3); its browser smoke uses synthetic Bifrost responses, so validate the Halo connection in a non-production environment before live use. | [jackmusick](https://github.com/jackmusick) | [Install and access requirements](https://github.com/jackmusick/HaloSqlStudio#install-from-this-repository) |

**Maintenance and support:** gobifrost maintains solutions hosted under the `gobifrost` GitHub organization. Solutions hosted elsewhere are maintained by their authors; gobifrost does not maintain or support them. A listing is for discovery and does not certify a solution's security or suitability. Follow each repository's license, compatibility notes, and setup instructions, and test it in your own environment before production use.

### Add a solution

Your repository should include a `bifrost.solution.yaml` manifest, an explicit license, and installation instructions. Document the supported Bifrost version and required integrations, permissions, and configuration. Keep credentials and customer data out of both the source and Git history; make installation-specific values configurable.

Add a table entry with the solution's name, a short description, and links to its public repository and setup instructions. State the maintainer and compatibility requirements in the entry. Open bugs and request features in the solution's repository.

## Workspace examples

The code in this repository contains modules, AI agents, workflows, and apps to adapt to your own workspace. Use an AI agent with the Bifrost skill to port the pieces you need and configure them for your environment.

### Features

**HaloPSA Report Agent** — An AI agent that generates HaloPSA SQL reports from natural language. Searches its knowledge base for schema patterns, writes and executes queries, iterates on errors, and saves what it learns for next time.

**Microsoft CSP App** — A React application for managing Microsoft CSP tenants. Links tenants to Bifrost organizations, handles application consent, manages GDAP relationships and role assignments, and provides batch operations.

**AutoElevate Integration** — An AI agent that reviews AutoElevate privilege elevation requests against your approval policy and autonomously approves, creates rules, or escalates to a human tech.

### Modules (MSP Integration SDKs)

| Module | Description |
|--------|-------------|
| `modules/halopsa.py` | HaloPSA PSA platform |
| `modules/autoelevate.py` | AutoElevate privilege elevation (with TOTP MFA) |
| `modules/ninjaone.py` | NinjaOne RMM |
| `modules/huntress.py` | Huntress EDR |
| `modules/itglue.py` | IT Glue documentation (US/EU/AU) |
| `modules/pax8.py` | Pax8 distributor (OAuth2) |
| `modules/cove.py` | Cove Data Protection / N-able Backup |
| `modules/sendgrid.py` | SendGrid email |
| `modules/immybot.py` | ImmyBot software deployment |
| `modules/microsoft/` | Microsoft Graph, CSP, GDAP, Exchange, Auth |

### Extension Helpers

| Extension | Description |
|-----------|-------------|
| `modules/extensions/halopsa.py` | Pagination, enriched tickets, batch ops, SQL execution, ticket creation |
| `modules/extensions/ninjaone.py` | Remote PowerShell execution via fetch-and-execute pattern |
| `modules/extensions/sendgrid.py` | Higher-level email sending with integration config |
| `modules/extensions/permissions.py` | Bifrost RBAC role-checking and authorization |

### Shared Tools

- **HaloPSA tools** — Auth-checked ticket operations, notes, agreements, time entry
- **Microsoft tools** — Email via Graph API, Exchange data providers
- **Bifrost utilities** — Organization management, role management, permissions

## Use the workspace examples

The recommended way to use this repo is to have an AI agent (e.g., Claude Code with the Bifrost skill) read the code here and port the relevant pieces into your own workspace. This lets you adapt modules, workflows, and patterns to your specific environment rather than trying to maintain a fork.

For Bifrost documentation, see [docs.gobifrost.com](https://docs.gobifrost.com).

### Configuration Reference

Key config values used by included features:

| Config | Used By | Description |
|--------|---------|-------------|
| `autoelevate_approval_policy` | Elevation Agent | Your approval policy text |
| `autoelevate_approval_email_template_id` | Elevation Agent | HaloPSA email template for approvals |
| `autoelevate_denial_email_template_id` | Elevation Agent | HaloPSA email template for denials |
| `ninja_script_id` | NinjaOne Extension | Pre-deployed script ID for remote execution |

The Microsoft CSP app also needs a `RESELLER_LINK` in `apps/microsoft-csp/components/TenantTable.tsx` set to your Partner Center reseller invitation URL.

## Contributing workspace examples

Contributions are welcome! Add reusable workspace examples here, or link an independently maintained solution in the index above.

1. Fork the repo
2. Create a feature branch
3. Add your module, workflow, or app
4. Submit a pull request

Please ensure any contributed code is generalized (no org-specific IDs, credentials, or customer data).

## License

The workspace examples in this repository are MIT licensed. Linked solutions have their own licenses.
