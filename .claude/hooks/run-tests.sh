#!/bin/bash
# Stop hook: run tests after Claude finishes responding
# Only runs if source files were likely modified (checks git status)

PROJECT_DIR="/home/joelle/Documents/code/titantron"

# Check if any source files changed
CHANGED=$(cd "$PROJECT_DIR" && git diff --name-only HEAD 2>/dev/null)

if [ -z "$CHANGED" ]; then
    exit 0
fi

RESULTS=""
FAILED=0

# Run backend tests if Python files changed
if echo "$CHANGED" | grep -q '\.py$'; then
    BACKEND_OUT=$(cd "$PROJECT_DIR/backend" && .venv/bin/python -m pytest tests/ -q --tb=line 2>&1)
    BACKEND_EXIT=$?
    if [ $BACKEND_EXIT -ne 0 ]; then
        FAILED=1
        RESULTS="Backend tests FAILED:\n$BACKEND_OUT"
    fi
fi

# Run frontend tests if TS/Svelte files changed
if echo "$CHANGED" | grep -qE '\.(ts|svelte)$'; then
    FRONTEND_OUT=$(cd "$PROJECT_DIR/frontend" && npx vitest run --reporter=verbose 2>&1 | tail -5)
    FRONTEND_EXIT=$?
    if [ $FRONTEND_EXIT -ne 0 ]; then
        FAILED=1
        RESULTS="$RESULTS\nFrontend tests FAILED:\n$FRONTEND_OUT"
    fi
fi

if [ $FAILED -ne 0 ]; then
    echo -e "$RESULTS" >&2
    exit 2
fi

exit 0
