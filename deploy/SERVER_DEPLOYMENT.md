# Server Deployment

This guide assumes a Linux server with Docker Engine and Docker Compose available.

## 1. Prepare the host

Clone the repository and enter it:

```bash
git clone <your-repo-url> PM
cd PM
```

Create the Docker env file:

```bash
cp .env.docker.example .env
```

Edit `.env` before exposing the site publicly:

- set `MINIMAX_API_KEY`
- keep `MINIMAX_BASE_URL=https://api.minimaxi.com/v1` unless your account explicitly uses the international endpoint
- set `PM_AGENT_SITE_ADDRESS` to your public domain such as `research.example.com`
- keep `PM_AGENT_ALLOW_PUBLIC_REGISTRATION=false` for public servers
- optionally set `PM_AGENT_REGISTRATION_INVITE_CODE=...`
- if web and API are split across different public origins, also set:
  - `PM_AGENT_CORS_ORIGINS=https://your-web-origin.example`
  - `PM_AGENT_AUTH_COOKIE_SAMESITE=none`

Those registration env vars are the deploy-time defaults. After the first admin is created, `/settings/admin` can override the live registration policy without editing `.env` or restarting the stack.
The recommended public path is now `docker-compose.prod.yml`, which uses Caddy to terminate HTTPS directly inside the stack.

## 2. Start the stack

Recommended public entrypoint:

```bash
./scripts/docker_deploy_prod.sh --admin-email admin@example.com --admin-password 'change-me-now'
```

What that does:

- validates the production env and compose config
- starts `postgres`, `redis`, `object-storage`, `api`, `worker`, and `web`
- bootstraps the first admin before opening the public entrypoint when admin credentials are provided
- starts `caddy`, which serves the website on one domain with automatic HTTPS

Useful variants:

```bash
./scripts/docker_preflight_check.sh --prod
./scripts/docker_deploy_prod.sh --pull --admin-email admin@example.com --admin-password 'change-me-now'
./scripts/docker_deploy_prod.sh --skip-build --admin-email admin@example.com --admin-password 'change-me-now'
```

Staging / existing external reverse proxy path:

```bash
./scripts/docker_deploy.sh
```

## 3. Verify

Useful checks:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy web api worker
curl -I https://your-domain.example
curl https://your-domain.example/api/health
curl https://your-domain.example/api/auth/public-config
```

Bootstrap flow:

1. Prefer passing `--admin-email` and `--admin-password` to `docker_deploy_prod.sh`, so the first admin is created before the public entrypoint opens
2. If you skipped that during deploy, run `./scripts/docker_bootstrap_admin.sh --prod --email admin@example.com --password 'change-me-now'`
3. Open `/login` and sign in with that admin account
4. Use `/settings/admin` to switch registration policy, issue invite codes, adjust roles, disable or re-enable accounts, and reset member passwords
5. The last active admin cannot be disabled, which protects the deployment from losing all admin access

Isolated auth smoke test:

```bash
COMPOSE_PROJECT_NAME=pm-smoke-prod PM_AGENT_SITE_ADDRESS=:80 PM_AGENT_HTTP_PORT=18080 PM_AGENT_HTTPS_PORT=18443 ./scripts/docker_deploy_prod.sh --admin-email admin@example.com --admin-password 'adminpass123'
```

Use `http://127.0.0.1:18080/login` for a disposable production-stack smoke test. When finished, tear it down with:

```bash
COMPOSE_PROJECT_NAME=pm-smoke-prod docker compose -f docker-compose.prod.yml down -v
```

## 4. Upgrade

```bash
git pull
DOCKER_COMPOSE_FILES=docker-compose.prod.yml ./scripts/docker_backup_state.sh
./scripts/docker_deploy_prod.sh --pull
```

If you changed frontend env such as `PM_AGENT_NEXT_PUBLIC_API_BASE_URL`, do not skip the rebuild.

## 5. Persistent data

By default Docker stores data across multiple named volumes:

- `pm_agent_postgres`: durable metadata
- `pm_agent_object_storage`: report/assets object payloads
- `pm_agent_redis`: queue / fanout persistence
- `pm_agent_state`: logs, cache, and compatibility scratch files

When you use the bundled production Caddy service, backups also need:

- `caddy_data`: TLS certificates and ACME account data
- `caddy_config`: Caddy runtime state

Your `.env` file is not part of those volumes. Back it up separately.

Use [`BACKUP_AND_RECOVERY.md`](deploy/BACKUP_AND_RECOVERY.md) for the multi-volume backup and restore flow.

## 6. HTTPS and reverse proxies

The recommended public stack already includes HTTPS termination via Caddy in `docker-compose.prod.yml`.

Common production patterns are now:

- use the bundled Caddy stack directly on a VM or bare-metal host with ports `80/443`
- or still place this stack behind your cloud load balancer if your platform requires it

When TLS is terminated upstream instead of by bundled Caddy:

- keep `X-Forwarded-Proto` forwarded to the API path
- keep same-origin deployment when possible, because cookies and SSE are simpler there
- if you are not using bundled Caddy, you can still fall back to `docker-compose.yml` plus your own reverse proxy

## 7. Backups and recovery

See [BACKUP_AND_RECOVERY.md](deploy/BACKUP_AND_RECOVERY.md).
