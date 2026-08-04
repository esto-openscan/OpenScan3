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
`/api/v0.9/system/update/status`. Repair endpoints are mounted the same way,
for example `/api/latest/system/repair/openscan3`.

| Method | Path | Backend action |
| --- | --- | --- |
| `GET` | `/system/update/status` | Runs `sudo /usr/bin/openscan-updater status --json` |
| `POST` | `/system/update/check` | Runs the combined update check: OpenScan dry-run, then system update check |
| `POST` | `/system/update/apply` | Schedules the fixed OpenScan-plus-system update flow in an independent transient systemd service |
| `POST` | `/system/update/openscan` | Runs `sudo /usr/bin/openscan-updater update --json` |
| `POST` | `/system/update/healthcheck` | Runs `sudo /usr/bin/openscan-updater healthcheck --json` |
| `GET` | `/system/update/logs` | Returns the last 200 lines from fixed updater log files |
| `POST` | `/system/repair/openscan3` | Runs `sudo /usr/bin/openscan-updater repair --json` |

The user-facing update button should use `/system/update/check` for planning
and `/system/update/apply` for execution. Apply returns `status: installing`
after `openscan-update-apply.service` was scheduled. That transient service is
outside the firmware service cgroup, so upgrading `openscan3-firmware` may
restart the API without interrupting dpkg. The detached flow updates OpenScan
packages first and then applies the classified system update.

`/system/update/openscan` remains available as a narrower OpenScan-only action
for recovery and compatibility. It does not apply Raspberry Pi OS or other
system package updates.

OpenScan3 v1 does not expose full system rollback, Debian package rollback,
kernel/firmware rollback, arbitrary package downgrades, package-name request
parameters, or a version chooser. Recovery is repair/forward-fix based:
reinstall OpenScan components, restore the known-good camera stack according to
the manifest, reapply protections, restart services, and run healthcheck.

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
- The combined apply endpoint does not merge OpenScan and system policy. It
  schedules one fixed updater command with no request-controlled arguments.

Scheduling and repair requests are protected by a process-local async lock.
The detached update and updater repair paths use the shared file lock at
`/var/lock/openscan-updater.lock`; the fixed transient unit name also prevents
two detached apply jobs from running at once.

Before starting `update`, combined update apply, or `repair`, the backend checks
the task manager for active `scan_task`
entries in `pending`, `running`, or `paused` state. If such a task is found, the
endpoint returns `409 Conflict` and does not call the updater.

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
structured errors. Updater policy and repair results, including blocked updates
and partial repair failures, are propagated as updater results instead of
treated as backend crashes.

## Future Work

Normal webclient presentation, richer progress reporting, and channel switching
UI are intentionally separate frontend work.
