Run static type checking on both backend and frontend and report issues.

## Steps

1. Run mypy on backend: `cd /home/joelle/Documents/code/titantron/backend && python -m mypy app/ --ignore-missing-imports`
2. Run svelte-check on frontend: `cd /home/joelle/Documents/code/titantron/frontend && npx svelte-check --tsconfig ./tsconfig.json`
3. Summarize:
   - Total errors and warnings per suite
   - Group related issues together
   - For critical type errors, suggest fixes
   - Ignore minor issues like missing third-party stubs
