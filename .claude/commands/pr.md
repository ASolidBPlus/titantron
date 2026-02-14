Run all quality checks and then create a pull request.

## Steps

1. Run the full quality suite (stop on first failure category):
   - `cd /home/joelle/Documents/code/titantron/backend && python -m ruff check app/ tests/` (lint)
   - `cd /home/joelle/Documents/code/titantron/backend && python -m pytest tests/ -v --tb=short` (tests)
   - `cd /home/joelle/Documents/code/titantron/frontend && npm test` (frontend tests)
   - `cd /home/joelle/Documents/code/titantron/frontend && npx svelte-check --tsconfig ./tsconfig.json` (typecheck)
2. If any checks fail, report the failures and ask the user if they want to proceed anyway
3. If all pass (or user approves), create the PR:
   - Analyze git diff against main
   - Draft a concise title and summary
   - Create the PR with `gh pr create`
4. Report the PR URL
