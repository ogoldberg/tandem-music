# loopkit coordination branch

Orphan branch holding distributed task locks for swarm-task-lock.sh.

Layout:

    locks/tasks/<task_id>.lock        — per-task lock files
    locks/heartbeats/<agent_id>.json  — per-agent liveness

Do not merge this branch into main.
Do not edit by hand — use plugin/scripts/swarm-task-lock.sh.