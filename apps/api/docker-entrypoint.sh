#!/bin/sh
set -eu

# Docker creates named-volume roots as root.  Initialise only the two durable
# TA01 paths before dropping privileges; the API/Worker process itself remains
# the unprivileged alphadesk user.
checkpoint_dir="${ALPHADESK_AI_RESEARCH_CHECKPOINT_DIR:-/app/checkpoints/ai-research}"
artifact_dir="${ALPHADESK_AI_RESEARCH_ARTIFACT_DIR:-/app/artifacts/ai-research}"

for directory in "$checkpoint_dir" "$artifact_dir"; do
    mkdir -p "$directory"
    chown alphadesk:alphadesk "$directory"
done

exec runuser -u alphadesk -- "$@"
