# Delta: persistence-storage

## ADDED Requirements

### Requirement: Capture artifacts
Artifacts SHALL be objects keyed from the capture's bundle key (`captures/Y/M/<id>.<name>`), written before the
capture row, listed by name from the object store, and deleted with the bundle; no table holds them. Refs: D-1421.
