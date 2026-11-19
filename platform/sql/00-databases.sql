-- Runs in the homelab database on first init and again on every deploy, so it must be repeatable.
-- CREATE DATABASE cannot run inside a transaction block; the query builds the statement only when the
-- database is missing and \gexec runs it.
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')
\gexec
