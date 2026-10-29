# THEAZ NMS recovery phase — 29 October 2026

## Scope

This is a local, isolated recovery branch based on source commit `2147a12`. The original source checkout and verified project archive were preserved. No server, DNS, reverse proxy, WireGuard, firewall, Docker service, or device configuration was changed. LibreNMS remains the production monitoring service on `nms.azrilachdi.web.id`.

The platform remains read-only for infrastructure configuration. Device configuration is performed through the native device GUI. Existing monitoring, inventory, service discovery, Proxmox integration, AI Assistant, alerts, logs, reports, users, audit, topology persistence, and native GUI portal features remain in the source baseline.

## Changes in this phase

- Removed the former RouterOS preview/apply and Proxmox guest-operation backend, associated route allowlists, adapter package, and mutation tests. Kept RouterOS read-only data queries and inventory metadata management.
- Reworked device onboarding as a four-step wizard: management address/identity, supported monitoring method, connection and credential guidance, then an explicit connection test. ICMP, TCP, HTTP(S), DNS, RouterOS API-SSL and Proxmox API are described; SNMP and SSH show as unavailable rather than implying active polling. The server reports actual test status.
- Added `Backup & Restore perangkat` with role-scoped UI/API, encrypted persistent files, scheduled/manual export, retention, SHA-256, version history, download, diff, audit events, and a typed restore confirmation.
- Added a RouterOS export adapter that requires the verified read-only account, API-SSL with certificate/hostname verification, and `show-sensitive=no`. The current restore flow produces a file to review/import in the original GUI; NMS never applies it.
- Added a small login entrance animation with reduced-motion support. Existing server-persisted AI history/jobs and topology save/workspace recovery remain intact.
- Improved isolated GUI session handling: transient NMS API outages no longer immediately close an active browser session (the browser broker lease still expires after 90 seconds without renewal), session-start polling retries without overlapping requests, and a dropped display can be reattached to the same browser session.

## Backup limits

Only an inventory entry bound to the existing `routeros-default` profile at the configured MikroTik host is currently supported. Cisco SF200-24, TP-Link, Proxmox, Technitium DNS, Portainer, Nginx Proxy Manager and other services do not yet have tested configuration-export adapters. Their monitoring or portal capability is separate from backup support.

The adapter requires a read-only RouterOS account with verified `read` + `api` policies and a trusted TLS certificate. If policy verification or TLS checks fail, backup is rejected. Export responses are capped at 1,300,000 bytes to stay under the authenticated API's 2 MiB JSON response ceiling. Backups are encrypted with AES-GCM under a domain-separated key derived from `NMS_CREDENTIALS_KEY`; changing that master key makes existing device backups unreadable. Retention is configurable from 2 to 100 versions. Automatic pre/post snapshots around GUI edits are not possible because the native GUI is external and NMS has no configuration-write mechanism.

## Verification

- Frontend unit tests: 86/86 passing after updating the navigation module count and backup endpoint checks.
- Frontend lint: passing.
- Frontend production build: passing; Vite still reports the existing large ApexCharts/topology chunks and the upstream `@maxgraph/core` `eval` warning.
- Backend pytest: 283 passed, 43 subtests passed, 4 upstream `python-telegram-bot` deprecation warnings. Backup tests use a mocked RouterOS export, not a live router.
- Access gateway/broker tests: 14 passed, 2 Linux-only tests skipped on Windows, 6 subtests passed. The skipped tests cover Unix file transfer/WebSocket relay; no real Chromium GUI worker or full remote display was started.
- Browser-based visual smoke test could not run because local browser use is disabled by Work settings. The Vite production build was checked instead.
- No authenticated test against the production dashboard, real device export, restore import, AI provider, or public isolated-GUI route was run in this phase. THEAZ is currently stopped in production, and no activation was made.

## Next safe stage

Review this branch and its test results before production installation. Production activation would replace LibreNMS at the same hostname or require a distinct approved hostname/routing plan; any backend, browser-runtime, or proxy change should be staged separately and explicitly approved. Do not enable device backup until the live RouterOS profile passes the read-only account and TLS checks.
