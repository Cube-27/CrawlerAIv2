## ADDED Requirements

### Requirement: Learning simulation
`crawlerai eval learn-sim` SHALL run learning on each dev host's first pages (per schema), replayed cold, and report
aggregates only by category: the zero-touch share (configs activated with no role A call), the activated share, config
fields per host and role A's calls and estimated cost; role A abstains unless asked to run, with a bound on its calls.
Refs: D-1685.
