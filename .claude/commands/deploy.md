Trigger a deployment to the testing environment via Komodo.

## Steps

1. Confirm with the user that they want to deploy to testing
2. Trigger PullStack via Komodo API:
   ```bash
   curl -s -X POST http://192.168.0.250:9120/execute/PullStack \
     -H "X-Api-Key: $KOMODO_KEY" \
     -H "X-Api-Secret: $KOMODO_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"stack": "titantron"}'
   ```
3. Wait 5 seconds, then trigger DeployStack:
   ```bash
   curl -s -X POST http://192.168.0.250:9120/execute/DeployStack \
     -H "X-Api-Key: $KOMODO_KEY" \
     -H "X-Api-Secret: $KOMODO_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"stack": "titantron"}'
   ```
4. Report success or failure. The app should be available at https://titantron-testing.dinfra.cloud/
