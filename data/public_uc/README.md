# Public UC benchmarks

These 28 files are unmodified downloads from the UnitCommitment.jl v0.3
benchmark collection on 2026-09-18 and 2026-09-19. Each compressed JSON
embeds its original `LICENSE` and `SOURCE` text.

The collection contains all twelve `or-lib/200_0_*_w` instances and the
selected Tejada19 24-hour sizes 214, 250, 290, 480, 505, 623, 647, 836, 850,
918, 931, 940, 957, 959, 1069, and 1130 generators.

The authoritative split membership and SHA-256 digest of every file are in
[`configs/public_uc_splits.json`](../../configs/public_uc_splits.json). The
test suite rejects a missing, changed, duplicated, or wrongly sized file.

Upstream base URL: <https://axavier.org/UnitCommitment.jl/0.3/instances/>.

The project reader deliberately supports only the selected single-bus thermal
subset. It rejects unsupported components rather than dropping them. The
project-owned PySCIPOpt formulation must be independently matched against the
official UnitCommitment.jl model before benchmark results are treated as
certified.
