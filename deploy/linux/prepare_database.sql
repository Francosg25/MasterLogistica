-- DBA only: run against a dedicated MasterLogistica database, before Alembic.
-- psql --dbname=APP_DATABASE --host=CLUSTER_HOST --username=DBA_ROLE --password --set=target_database=APP_DATABASE --file=prepare_database.sql
-- Assign passwords through the approved DBA secret-management process, not this file.
\set ON_ERROR_STOP on
\if :{?target_database}
\else
  \echo 'Specify target_database. No changes were applied.'
  DO $$ BEGIN RAISE EXCEPTION 'Specify target_database'; END $$;
\endif
SELECT current_database() = :'target_database' AND current_database() NOT IN ('postgres','template0','template1') AS correct_target \gset
\if :correct_target
\else
  \echo 'Wrong database. No changes were applied.'
  DO $$ BEGIN RAISE EXCEPTION 'Wrong database'; END $$;
\endif

BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='masterlogistica_app') THEN
    CREATE ROLE masterlogistica_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='masterlogistica_migrator') THEN
    CREATE ROLE masterlogistica_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='masterlogistica_app' AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
    RAISE EXCEPTION 'The API role has administrative privileges; review with the DBA';
  END IF;
END $$;
SELECT format('GRANT CONNECT ON DATABASE %I TO masterlogistica_app, masterlogistica_migrator', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM masterlogistica_app;
GRANT USAGE, CREATE ON SCHEMA public TO masterlogistica_migrator;
GRANT USAGE ON SCHEMA public TO masterlogistica_app;
COMMIT;

-- Alembic creates the objects with the migrator role and grants the specific API permissions.
-- Do not grant table ownership, TRUNCATE, DELETE or membership of the migrator role to the API.
