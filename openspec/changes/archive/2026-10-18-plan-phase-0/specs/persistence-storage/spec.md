# Persistence and Storage delta

## ADDED Requirements

### Requirement: One database
The system SHALL use one database, `crawlerai` (role `app`), created by `infra/postgres/init.sql`; eval pages,
captures and runs live in it. Refs: owner (2026-10-18, master plan decision 2).

## MODIFIED Requirements

### Requirement: One baseline migration (greenfield)
The database SHALL have exactly one Alembic baseline revision (`0001_baseline`); a model change edits it and
databases are recreated, never migrated with data steps or compatibility shims. (Previously: a private `p0001` too.)
Refs: Appendix A #43, D-0954.
#### Scenario: Migration round trip
- **WHEN** CI runs upgrade head, downgrade base, upgrade head on an empty database
- **THEN** all three succeed and constraint names match `test_baseline_migration.py`

### Requirement: Object stores and key layout
Bundles SHALL go through the `ObjectStore` protocol (`fs` and `s3` backends, S3 via boto3's environment chain, no
MinIO); escaping or malformed keys raise `ValueError`. (Previously: hidden and fresh bundles under a private root.)
Refs: §15, D-0094, D-0095, D-0096.
#### Scenario: Escaping key refused
- **WHEN** `put("../x", data)` is called on either backend
- **THEN** it raises `ValueError` and writes nothing

## REMOVED Requirements

### Requirement: Two databases with separate roles
