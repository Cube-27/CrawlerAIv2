-- Databases and roles for local development and CI.
CREATE ROLE app LOGIN PASSWORD 'app';

CREATE DATABASE crawlerai OWNER app;
