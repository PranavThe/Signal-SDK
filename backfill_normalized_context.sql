-- Backfill normalized_context for escalations that have NULL
UPDATE escalations
SET normalized_context = '{}'::jsonb
WHERE normalized_context IS NULL;
