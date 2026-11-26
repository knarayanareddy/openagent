---
name: watchlist
description: "Playbook: watch a list of topics, repos or people and report only what changed."
schedule: 0 */4 * * *
---
# Watchlist

1. Read the watch items from the person's settings (`items`).
2. For each, check the current state with read-only tools.
3. Compare with the last report in memory; report only differences.
4. If nothing changed, reply exactly [quiet].
