#!/bin/bash
# PostToolUse hook: auto-deploy after git push to main
# Triggers on Bash tool — filters to only git push commands

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only trigger on git push to main
if ! echo "$COMMAND" | grep -qE 'git push.*main'; then
    exit 0
fi

KOMODO_URL="http://192.168.0.250:9120/execute"
API_KEY="K-nkoV5vDXWyvSfjxEcqStTNiwARQzovY1DJ73wsXc"
API_SECRET="S-8Cb3m3mlyerJqHt7eNifHsGkGc2vr8PdawnXLwpw"
GH_API="https://api.github.com/repos/ASolidBPlus/titantron/actions/runs?per_page=1"

echo "Waiting for CI build..." >&2

# Poll GitHub Actions until build completes (max 5 min)
for i in $(seq 1 20); do
    RESULT=$(curl -sf -H "Accept: application/vnd.github+json" "$GH_API" 2>/dev/null)
    STATUS=$(echo "$RESULT" | jq -r '.workflow_runs[0].status // "unknown"')
    CONCLUSION=$(echo "$RESULT" | jq -r '.workflow_runs[0].conclusion // "null"')

    if [ "$STATUS" = "completed" ]; then
        if [ "$CONCLUSION" != "success" ]; then
            echo "CI build failed ($CONCLUSION) — skipping deploy" >&2
            exit 2
        fi
        break
    fi

    if [ "$i" -eq 20 ]; then
        echo "CI build timed out after 5 min — skipping deploy" >&2
        exit 2
    fi

    sleep 15
done

echo "CI passed. Pulling latest image..." >&2

# Pull stack
curl -sf -X POST "$KOMODO_URL" \
    -H "X-Api-Key: $API_KEY" \
    -H "X-Api-Secret: $API_SECRET" \
    -H "Content-Type: application/json" \
    -d '{"type":"PullStack","params":{"stack":"titantron","services":[]}}' >/dev/null

sleep 10

echo "Deploying..." >&2

# Deploy stack
curl -sf -X POST "$KOMODO_URL" \
    -H "X-Api-Key: $API_KEY" \
    -H "X-Api-Secret: $API_SECRET" \
    -H "Content-Type: application/json" \
    -d '{"type":"DeployStack","params":{"stack":"titantron","services":[],"stop_time":null}}' >/dev/null

sleep 15

# Verify
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "https://titantron-testing.dinfra.cloud/api/v1/admin/status" 2>/dev/null)

if [ "$HTTP_CODE" = "200" ]; then
    echo "Deployed successfully — app is live" >&2
else
    echo "Deploy may have failed — health check returned $HTTP_CODE" >&2
    exit 2
fi

exit 0
