# Local Automations

DPN AI automations are recurring local prompts that use the same agent, tools, projects, and audit controls as interactive operations.

## Schedule formats

- Interval: whole minutes from 1 to 10080. Example: `60`.
- Daily: local system time in 24-hour `HH:MM`. Example: `08:30`.

## Safety

Automations obey current web, image, command, and approval settings. Keep command execution disabled until the automation prompt has been reviewed. Every execution creates a separate conversation and run record.

## Runtime behavior

The scheduler runs only while the DPN AI server is open. Missed runs are not backfilled repeatedly; an overdue automation executes once and schedules its next run.