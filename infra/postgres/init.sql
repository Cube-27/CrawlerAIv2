-- Databases and roles for local development and CI (SPEC-00 §4.4, SPEC-03 §4.1).
-- The private eval database is owned by `custodian`, and `app` gets nothing on it (C1). The `custodian` role
-- cannot log in here: custodians set up their own credentials, outside the repo.
CREATE ROLE app LOGIN PASSWORD 'app';
CREATE ROLE custodian NOLOGIN;

CREATE DATABASE crawlerai OWNER app;
CREATE DATABASE crawlerai_eval_private OWNER custodian;
REVOKE ALL ON DATABASE crawlerai_eval_private FROM PUBLIC;
