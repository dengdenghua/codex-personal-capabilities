# Verification — v1.0.0

2026-11-13:

- 10 plugin packages / 81 SKILL.md entries collected; duplicate skill names can exist in separately namespaced plugins.
- 6 regression tests passed: missing-runtime failure, argument-array handling, invalid configuration, private-file blocking, credential detection, repository privacy check.
- Official Codex CLI installed all 10 packages successfully in a clean isolated CODEX_HOME, without changing the user's active Codex configuration.
- Known credential-pattern and private-file checks passed. A generic OAuth fallback string in the original Quark client was manually reviewed; it is not an account token. Public standards URL matches were excluded with a word boundary rather than whitelisting files.
- Original machine paths removed from portable skill documentation. No account config, private database, model, history or original project archive included.
- Native commercial software, original externally installed Blender/KiCad/SolidWorks server environments and authentication are not included or validated on a second physical computer. Their requirements are explicit in RUNTIMES.md.
- Machine-local excluded-file inventory and detailed install log stay outside the repository.

This verifies source packaging, Codex installation and portable launcher behavior, not every skill's external service or native CAD operation. Refresh the hash manifest after intentional versioned edits.
