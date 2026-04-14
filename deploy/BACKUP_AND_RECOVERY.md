# Backup And Recovery

The flagship Docker deployment always stores data across these core named volumes:

- `pm_agent_postgres`
- `pm_agent_object_storage`
- `pm_agent_redis`
- `pm_agent_state`

When you deploy the production Caddy gateway, the backup scripts also include:

- `caddy_data`
- `caddy_config`

## What is included

The backup archive now bundles the compose-managed volumes for:

- PostgreSQL metadata
- object storage contents
- Redis append-only queue/fanout data
- `/data/state` scratch files and logs
- Caddy TLS certificates and ACME account/config state when the active compose file defines those volumes

It still does not include `.env`, bind-mounted config files such as `deploy/caddy/Caddyfile`, secrets outside the containers, or your git checkout.

## Backup

Create a timestamped archive:

```bash
./scripts/docker_backup_state.sh
```

Write to a specific file:

```bash
./scripts/docker_backup_state.sh ./backups/pm-agent-state-latest.tar.gz
```

The script backs up the compose-managed Docker volumes into one archive. Back up `.env` separately and store it securely.

## Restore

Restore the default stack volumes and restart the stack:

```bash
./scripts/docker_restore_state.sh ./backups/pm-agent-state-20260411T000000Z.tar.gz --yes
```

Restore a single custom Docker volume without restarting the app:

```bash
./scripts/docker_restore_state.sh ./backups/pm-agent-state-20260411T000000Z.tar.gz --volume-name pm-agent-restore-test --yes --skip-start
```

## Operational advice

- Prefer taking backups before upgrades.
- For the cleanest snapshot, avoid active writes during backup if possible.
- Always stop the live stack before restoring the default compose-managed volumes.
- Keep at least one off-host copy of backup archives.
- Test restores periodically on a temporary volume, not only on production.

## Suggested runbook

Before deploy:

```bash
./scripts/docker_backup_state.sh
```

Upgrade:

```bash
git pull
./scripts/docker_deploy.sh --pull
```

Recover:

```bash
./scripts/docker_restore_state.sh ./backups/<archive>.tar.gz --yes
docker compose ps
docker compose logs --tail=100 gateway caddy web api worker
```
