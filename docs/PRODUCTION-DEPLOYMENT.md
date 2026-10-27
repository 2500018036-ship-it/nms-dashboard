# Production deployment

Public URL: https://nms.azrilachdi.web.id

Traffic path: Azure gateway `20.194.8.143` (Nginx / Let's Encrypt) Ã¢â€ â€™ web server `192.168.20.195:80` (existing Nginx Proxy Manager) Ã¢â€ â€™ `nms-dashboard:8080` Ã¢â€ â€™ existing `nms-bot:8765` for `/nms-api/` requests. All application containers and monitoring data stay on `192.168.20.195`. The backend's loopback port is not published to the internet.

## CI/CD

Push to `main` runs lint, frontend tests and a production build in GitHub Actions. Pull requests run these checks without publishing. A passing main build produces a Docker image labelled with the exact commit, smoke tests the container, and publishes the compressed image plus its SHA-256 in an immutable release named `deploy-<commit>`.

The root-owned systemd timer on the web server checks the latest release every 60Ã¢â‚¬â€œ70 seconds. It downloads the image from the fixed repository URL, verifies its checksum and revision, then applies Docker Compose and checks container health and authenticated API protection. An unsuccessful rollout restores the previous image and blocks repeated deployment of the failed commit. The final Actions job waits for HTTPS to report its commit and verifies API protection before succeeding. No SSH password or private key is stored in GitHub Actions.

Compose and the deployment helper are server infrastructure. A code release updates the image; edits to Compose, systemd units or the helper must also be installed on the server by an administrator.

## Server files

- `/mnt/data/www/nms-dashboard/compose.yaml`: root-owned production Compose file.
- `/usr/local/sbin/nms-dashboard-pull-release`: installed copy of `deploy/pull-release.sh`.
- `/etc/systemd/system/nms-dashboard-deploy.{service,timer}`: deployment service and schedule.
- `/var/lib/nms-dashboard-deploy/`: current/previous image, release metadata and deployment lock.
- `/mnt/data/nginx-proxy-manager/data/nginx/custom/nms-dashboard.conf`: NMS internal virtual host, included from `http.conf`.
- Gateway `/etc/nginx/sites-available/nms.azrilachdi.web.id`: domain proxy and Certbot-managed TLS.

Required existing Docker networks: `web-proxy`, `nms-bot_default`. The NMS backend, database, sessions, encrypted credentials and collector configuration remain managed by the existing `/mnt/data/www/nms-bot` installation.

## Operations

```bash
sudo systemctl status nms-dashboard-deploy.timer
sudo journalctl -u nms-dashboard-deploy.service -n 50 --no-pager
sudo docker ps --filter name=nms-dashboard
sudo cat /var/lib/nms-dashboard-deploy/current-revision
```

Manual deployment check: `sudo systemctl start nms-dashboard-deploy.service`.

To retry a failed commit after resolving an infrastructure issue, remove only `/var/lib/nms-dashboard-deploy/blocked-revision`, then start the service. Prefer fixing application issues with a new commit.

To roll back manually, stop the timer, copy `previous.env` to `release.env`, and run:

```bash
sudo systemctl stop nms-dashboard-deploy.timer
sudo cp /var/lib/nms-dashboard-deploy/previous.env /var/lib/nms-dashboard-deploy/release.env
sudo docker compose --project-name nms-dashboard --env-file /var/lib/nms-dashboard-deploy/release.env -f /mnt/data/www/nms-dashboard/compose.yaml up -d --no-build --wait
```

Leave the timer stopped until a corrected release is available. Do not prune the previous release image before completing validation.

## Public API gateway

The frontend is built with `VITE_NMS_API_ENABLED=true` and `VITE_NMS_API_BASE=/nms-api`. The container verifies the public HTTPS Origin and rejects cross-site requests before translating Host/Origin to the backend's existing loopback contract. Basic Authorization is removed; users authenticate through NMS sessions. Session cookies receive Secure, HttpOnly and SameSite=Strict flags at the gateway. Existing dashboard accounts remain valid; their passwords are not in this repository.

## Backend releases

Releases now contain both `nms-dashboard:<commit>` and `nms-backend:<commit>`. The manifest includes `backend: true`. `deploy/backend.compose.yaml` overrides only the existing backend image; the original Compose project, credentials and data paths remain in use. Keep `NMS_BACKEND_IMAGE` in both current and rollback environment files. Stop the timer before manual rollback and restore both images with their respective Compose files. See the device stability report for enrollment and DHCP behavior.
