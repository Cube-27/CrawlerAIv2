## MODIFIED Requirements

### Requirement: Learning simulation
`crawlerai eval learn-sim` SHALL run learning on each dev host's first pages (per schema), replayed cold, and report
aggregates only by category: the zero-touch share (configs activated with no role A call), the activated share, config
fields per host, the config fields in each executability class, and role A's calls and cost; role A abstains unless
asked to run, with a bound on its calls, and a live role A's tokens, cache read and write tokens and cost at the
model's prices are reported. Refs: D-1685, D-1726.
(Previously: without the executability classes, and a live role A's cost estimated from characters only.)
