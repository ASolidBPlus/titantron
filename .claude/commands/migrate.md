Help create or apply an Alembic database migration.

## Steps

1. Ask the user what the migration is for (or check if there are pending model changes)
2. Generate a new migration:
   ```bash
   cd /home/joelle/Documents/code/titantron/backend && python -m alembic revision --autogenerate -m "description"
   ```
3. Read the generated migration file and review it:
   - Check that upgrade() and downgrade() look correct
   - Ensure idempotent patterns are used (check if column/table exists before creating)
   - Flag any destructive operations (dropping columns/tables)
4. If changes look good, apply:
   ```bash
   cd /home/joelle/Documents/code/titantron/backend && python -m alembic upgrade head
   ```
5. Report what was migrated
