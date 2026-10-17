## MODIFIED Requirements

### Requirement: Presets
The system SHALL ship the four presets under `backend/src/crawlerai/schemas/presets/`, every field mapped to a
schema.org path and described; "when shown" fields are optional and no preset holds a derived field (such as a
count of variants or images). A job's places are a list of locations (`locations`) in both job presets.
(Previously: `job_listing` had one `location`.) Refs: §5.3, D-0015, D-0245, D-0961, D-0967, D-1477.
