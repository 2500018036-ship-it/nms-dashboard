# Device management stability fixes â€” 27 October 2026

The registration failure for Cisco `192.168.10.26` was an exact-host monitoring policy rejection, hidden behind a generic HTTP 400 message. The address answered ICMP and Cisco SF200-24 advertised it through RouterOS neighbor discovery. Administrators can now authorize precisely the address being registered in the same atomic save. Network/Server Administrators retain their existing scope and cannot widen the allowlist. Validation codes are bounded and translated into specific UI messages.

All existing configured endpoints are enrolled into the same persistent inventory when the application starts. Matching hosts reuse existing records and collectors. Device Management shows this complete registry with edit, actual connection test and confirmed removal. A removed configured registration is not recreated on restart. Removal can explicitly detach its topology nodes and links in the same transaction; stale revisions abort the entire operation. Monitoring history is retained. Core shared infrastructure collectors remain governed by server configuration.

TLWR820N's MAC `20:E1:5D:91:53:DC` had a waiting lease at `192.168.30.194` while its active lease was `192.168.10.194`. The old address was unreachable, so the prior DOWN observation was accurate for that address. DHCP following now matches the exact MAC to a unique bound lease in an already configured private /24 subnet. The new address must answer an ICMP probe before its registration and exact-host policy are updated. Ambiguous, missing, disabled, truncated or out-of-scope leases never produce an UP status. The verified MAC for the existing ajilll target is tracked in the same way.

ICMP confirms a missed reply once before reporting DOWN. Manual connection tests bypass a stale cache and have sufficient time for a DHCP lookup. Fresh ICMP evidence of a reachable host is shown separately from unavailable API/resource collectors. Edited addresses do not display a previous address's sample as their current health.

Authenticated dashboard accounts now have separate request budgets behind the proxy. The frontend resumes polling after a temporary rate limit. Missing/expired samples and genuine unreachable targets continue to report UNKNOWN/DOWN.

The repository now includes the backend source in `backend/`. GitHub Actions runs both frontend and backend tests, builds both Docker images for one commit, and publishes both in the checked release archive. The pull deployment preserves the existing `nms-bot` Compose project, `.env`, data, collector mounts and credentials. A failed rollout restores the previous images. Backend database and source backups are kept privately on the server before the first rollout.

The NMS virtual host is included at the end of the NPM HTTP configuration (`http.conf`). This keeps the existing default HTTP host in place, including the internal server HTTP availability check.
