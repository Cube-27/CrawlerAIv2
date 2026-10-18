-- Databases and roles for local development and CI (SPEC-00 §4.4).
CREATE ROLE app LOGIN PASSWORD 'app';

CREATE DATABASE crawlerai OWNER app;
