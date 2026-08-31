# Autonomous Background Jobs

DPN AI v5 queues Direct operations, Missions, and Workflows in SQLite. Workers begin when the application starts. A job that was marked running during an unclean stop is returned to the queue at the next startup.

Jobs expose queued, running, completed, failed, and cancelled states, progress metadata, final results, errors, timestamps, cancellation, and retry.

Jobs do not run when DPN AI is closed. This is intentional: the standard release does not silently install an operating-system service. An operator who needs always-on behavior can run DPN AI under a service manager after configuring access tokens, file permissions, resource limits, and backups.