Run linters and formatters across the codebase, fix what you can, and report remaining issues.

## Steps

1. Run ruff on backend: `cd /home/joelle/Documents/code/titantron/backend && python -m ruff check app/ tests/ --fix && python -m ruff format app/ tests/`
2. Run eslint on frontend: `cd /home/joelle/Documents/code/titantron/frontend && npx eslint src/ --fix`
3. Run prettier on frontend: `cd /home/joelle/Documents/code/titantron/frontend && npx prettier --write 'src/**/*.{ts,svelte}'`
4. Report:
   - What was auto-fixed
   - Any remaining issues that need manual attention
