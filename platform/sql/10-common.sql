-- Runs in the homelab database on first init and again on every deploy: every statement is idempotent.

CREATE SCHEMA IF NOT EXISTS common;

CREATE TABLE IF NOT EXISTS common.audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now(),
    service varchar(40) NOT NULL,
    action varchar(80) NOT NULL,
    actor varchar(40) NOT NULL,
    actor_detail jsonb,
    device varchar(64),
    source_ip inet,
    turn_id varchar(64),
    trace_id varchar(32),
    span_id varchar(16),
    target_kind varchar(40),
    target_id varchar(120),
    before jsonb,
    after jsonb,
    result varchar(12) NOT NULL CHECK (result IN ('ok', 'denied', 'failed', 'pending')),
    error varchar(500),
    summary varchar(200),
    extra jsonb
);

CREATE INDEX IF NOT EXISTS audit_at_idx ON common.audit (at);
CREATE INDEX IF NOT EXISTS audit_actor_at_idx ON common.audit (actor, at);
CREATE INDEX IF NOT EXISTS audit_target_at_idx ON common.audit (target_kind, target_id, at);

-- Read-only role for the sql tool; the deploy gives it a login later.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jarvis_ro') THEN
        CREATE ROLE jarvis_ro LOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA common TO jarvis_ro;
GRANT SELECT ON common.audit TO jarvis_ro;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
