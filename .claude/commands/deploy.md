Deploy the latest code to the testing environment. Handles the full pipeline: wait for CI, pull image, verify.

## Environment

- GitHub repo: `ASolidBPlus/titantron`
- GHCR image: `ghcr.io/asolidbplus/titantron:latest`
- Komodo: `http://192.168.0.250:9120/`
- Komodo auth: read `KOMODO_KEY` and `KOMODO_SECRET` from `/home/joelle/Documents/code/titantron/.env`
- Stack name: `titantron`
- Live URL: `https://titantron-testing.dinfra.cloud/`

## Step 1: Wait for CI build to succeed

GitHub Actions builds a Docker image on push to main. Poll until complete:

```bash
curl -s -H "Accept: application/vnd.github+json" https://api.github.com/repos/ASolidBPlus/titantron/actions/runs?per_page=1
```

Check `workflow_runs[0].status` and `workflow_runs[0].conclusion`:
- If `status` is `in_progress` or `queued`: wait 15 seconds, poll again (up to 5 min)
- If `conclusion` is `success`: proceed to Step 2
- If `conclusion` is `failure`: STOP and report the failure. Do NOT deploy broken builds.

## Step 2: Pull latest image via Komodo

Auto-update is enabled on the stack, so pulling triggers an automatic deploy. No separate deploy step needed.

```bash
KOMODO_KEY=$(grep KOMODO_KEY /home/joelle/Documents/code/titantron/.env | cut -d= -f2)
KOMODO_SECRET=$(grep KOMODO_SECRET /home/joelle/Documents/code/titantron/.env | cut -d= -f2)
curl -s -X POST http://192.168.0.250:9120/execute \
  -H "X-Api-Key: $KOMODO_KEY" \
  -H "X-Api-Secret: $KOMODO_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"type":"PullStack","params":{"stack":"titantron","services":[]}}'
```

Wait 30 seconds for pull + auto-deploy to complete.

## Step 3: Verify deployment

1. Health check:
   ```bash
   curl -sf https://titantron-testing.dinfra.cloud/api/v1/admin/status
   ```
   Should return JSON with `required` and `authenticated` fields.

2. Smoke test core endpoints:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" https://titantron-testing.dinfra.cloud/api/v1/browse/promotions
   ```
   Should return 200.

3. If there was a specific fix being deployed, test that endpoint too.

## Reporting

Report a summary:
| Step | Result |
|------|--------|
| CI build | success/failure |
| Image pull + auto-deploy | success/failure |
| Health check | HTTP status |
| Smoke test | HTTP status |
