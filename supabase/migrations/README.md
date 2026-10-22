# Migrations

`db/schema.sql` is the baseline (v3) and is never edited again. Every change
after it is a numbered file here:

```
001_add_something.sql
002_backfill_something.sql
```

Show the SQL to the team before running it against the shared project. Two
people applying different ad-hoc changes to one Supabase database is the
failure that costs a day we do not have.
