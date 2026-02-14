Run the test suites for this project and report the results.

## Steps

1. Run backend tests: `cd /home/joelle/Documents/code/titantron/backend && .venv/bin/python -m pytest tests/ -v --tb=short`
2. Run frontend tests: `cd /home/joelle/Documents/code/titantron/frontend && npx vitest run`
3. Summarize results:
   - Total passed / failed / errors for each suite
   - For any failures, show the test name and a brief explanation of what went wrong
   - If a failure looks like a real bug (not a test issue), suggest a fix
