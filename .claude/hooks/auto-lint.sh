#!/bin/bash
# PostToolUse hook: auto-lint files after Edit/Write
# Receives JSON on stdin with tool_input.file_path

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

PROJECT_DIR="/home/joelle/Documents/code/titantron"

case "$FILE_PATH" in
    *.py)
        # Run ruff fix + format on the edited Python file
        "$PROJECT_DIR/backend/.venv/bin/python" -m ruff check --fix --quiet "$FILE_PATH" 2>/dev/null
        "$PROJECT_DIR/backend/.venv/bin/python" -m ruff format --quiet "$FILE_PATH" 2>/dev/null
        ;;
    *.ts|*.svelte)
        # Run prettier on the edited frontend file
        cd "$PROJECT_DIR/frontend" && npx prettier --write "$FILE_PATH" 2>/dev/null
        ;;
esac

exit 0
