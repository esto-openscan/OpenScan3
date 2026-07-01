# System Update API

The firmware backend exposes a narrow API wrapper around the local
`openscan-updater` command. The backend does not implement APT, dpkg, package
selection, or update policy logic itself.

Intended call path:

```text
webclient -> openscan3-firmware API -> sudo /usr/bin/openscan-updater <fixed-command> --json
```

The webclient must call the firmware API only. It must not call
`openscan-updater` directly.

## Endpoints

These routes are mounted under the normal firmware API version prefixes. On the
appliance, nginx maps `/api/...` to the backend, so clients should use
`/api/latest/system/update/status` or pin to
`/api/v0.9/system/update/status`.

| Method | Path | Backend action |
| --- | --- | --- |
| `GET` | `/system/update/status` | Runs `sudo /usr/bin/openscan-updater status --json` |
| `POST` | `/system/update/check` | Runs `sudo /usr/bin/openscan-updater check --dry-run --json` |
| `POST` | `/system/update/openscan` | Runs `sudo /usr/bin/openscan-updater update-openscan --json` |
| `POST` | `/system/update/healthcheck` | Returns `501` until the updater implements `healthcheck` |
| `GET` | `/system/update/logs` | Returns the last 200 lines from fixed updater log files |

Rollback is not exposed because the current updater CLI does not implement a
rollback command.

## Safety Model

- The backend uses a fixed command map and fixed argv lists.
- Request bodies and query strings cannot add package names, shell fragments, or
  arbitrary command arguments.
- `shell=True` is not used.
- Commands run with a minimal environment and bounded timeouts.
- The firmware process does not need to run as root; system integration is
  expected to provide narrow sudoers rules for the backend user.
- The logs endpoint reads only known updater log paths and returns a bounded tail.
- The updater remains responsible for APT safety classification and package
  policy decisions.

`update-openscan` is protected by a process-local async lock. A second update
request returns `409 Conflict` while one update command is already running. If
the backend is deployed with multiple worker processes, this lock is not enough;
add a shared file lock such as `/var/lock/openscan-updater.lock`.

Before starting `update-openscan`, the backend checks the task manager for active
`scan_task` entries in `pending`, `running`, or `paused` state. If such a task is
found, the endpoint returns `409 Conflict` and does not call the updater.

## Response Shape

Successful command execution returns structured JSON:

```json
{
  "ok": true,
  "command": "status",
  "backend_api_version": "1",
  "result": {}
}
```

Backend execution failures, command timeouts, and invalid updater JSON return
structured errors. Updater policy results, including blocked update results from
`update-openscan`, are propagated as updater results instead of treated as
backend crashes.

## Future Work

System, security, kernel, camera-stack, recovery, and rollback update modes are
future work and are intentionally not exposed by this API yet.
