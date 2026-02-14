#!/bin/bash
# PostToolUse hook: restart local backend after Python file edits
# Runs async so it doesn't block editing flow

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only trigger for backend Python files
case "$FILE_PATH" in
    */backend/app/*.py) ;;
    *) exit 0 ;;
esac

PROJECT_DIR="/home/joelle/Documents/code/titantron"

# Check if local dev server is running
if ! pgrep -f "uvicorn app.main:app.*8765" >/dev/null 2>&1; then
    exit 0
fi

# Kill and restart
pkill -f "uvicorn app.main:app.*8765" 2>/dev/null
sleep 1
cd "$PROJECT_DIR/backend" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 &

# Wait for ready
for i in $(seq 1 10); do
    if curl -sf http://127.0.0.1:8765/api/v1/admin/status >/dev/null 2>&1; then
        echo "Local backend restarted" >&2
        exit 0
    fi
    sleep 1
done

echo "Local backend failed to restart" >&2
exit 2
