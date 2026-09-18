Old data moved here on 15 Sep 2026, before the customer-tracking feature was added.

queries.jsonl  833 test questions typed into the chatbot (June-July 2026), mostly during development.
savora.db      old local SQLite database: 2 sessions, 2 test orders.

Nothing was deleted. To restore, move these files back:
  queries.jsonl -> logs/queries.jsonl
  savora.db     -> savora.db  (project root)

Note: the app's .env points at an online Supabase database, which was paused
(host no longer resolves) when this archive was made. Any orders stored there
are untouched.
