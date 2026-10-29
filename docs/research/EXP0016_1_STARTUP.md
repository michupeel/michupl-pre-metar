# EXP0016.1 — D-1 observer startup and crash recovery

Dedicated task: `MichuplPreMetar-D1Research-v1`. It does not control the weather,
HighTempTation, dashboard or EXP0015 tasks/processes. Installation registers the
task only: it does **not** start it, stop the existing observer, or replace an
already owned definition. Another task with the same name and different owner
description/action/working directory blocks installation and removal.

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv run python -m premetar.research.d1_service preview
uv run python -m premetar.research.d1_service install --apply
uv run python -m premetar.research.d1_service status
# Unregister this owned task only; leaves any running observer untouched:
uv run python -m premetar.research.d1_service remove --apply
```

The action uses the absolute existing `.venv\Scripts\python.exe`, absolute project
working directory, and `-m premetar.research.d1_service run`. There is no shell
wrapper, execution-policy bypass, wallet, password, elevation or credential file.
Structured preview includes exact action and an equivalent escaped XML audit
view. Native Task Scheduler cmdlets register and re-read the real configuration.

The current-user **logon trigger** is the safe credential-free fallback. It works
after interactive login without an open terminal; it does not run before login.
The user is not asked for a Windows password and no global security setting is
changed. Rights are Limited, logon type Interactive, parallel instances IgnoreNew,
execution timeout unlimited, restart after failure every60seconds at most3times,
battery operation permitted. Installation verifies these settings. It does not
claim that Windows reboot itself was tested.

The task entrypoint respects the observer's existing `stop.request` marker. A
verified live `monitor.lock` owner is a successful no-op (`ALREADY_RUNNING`), so
starting the task while manual/background collection is active neither duplicates
nor restarts the observer. Unknown lock ownership fails closed. Dead owned locks
are recovered by the existing OS-held single-writer implementation; history and
checkpoint state are retained. A simultaneous startup is rechecked after the
existing atomic lock rejects the losing process. No temporary unlock/relock gap
is introduced by the wrapper.

Normal failures exit nonzero for Task Scheduler's bounded restart policy. The
wrapper redirects Python stdout/stderr into `logs/epwa-d1-service.log`, rotating at
2MB with two backups. Error summary records exception class rather than raw
exception messages. Immutable study evidence remains in the existing bounded
EXP0016 journal. A deliberate normal stop is not treated as a crash.

Tests use synthetic task definitions and a bounded replacement monitor loop:
owned/unowned tasks, path escaping, settings, duplicate no-op, startup race,
unknown lock rejection and real local journal recovery without HTTP. They do not
register/remove system tasks or terminate any live process. Installation and
operational verification must be reported separately from these unit tests.
