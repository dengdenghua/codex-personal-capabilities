# Verification — v1.1.0

2026-11-13, Windows x64:

- 10 plugin packages / 81 SKILL.md entries; 17 automated regression tests passed.
- 303 Python source files parsed successfully; source, privacy, plugin manifests and SHA256 inventory checks passed.
- Installed Python dependencies into isolated per-service virtual environments; each passed pip check. REA installed with npm ci from the repaired cross-platform lock file, using Node 24.22.1 verified against nodejs.org SHA256.
- The Install.ps1 entry point installed all 10 packages through the official Codex CLI in a fresh, separate CODEX_HOME. Active Codex configuration was not modified.
- Both direct runtime startup and the six installed plugin launchers passed real MCP initialize / tools/list checks:

| Service | Tools returned |
|---|---:|
| SolidWorks | 42 |
| KiCad | 9 |
| Blender | 26 |
| LightTools | 26 |
| Zemax | 32 |
| REA | 229 |

- Repeated setup reused existing environments. Managed configuration merging is idempotent, preserves local custom values and retains unrelated custom servers. Runtime-owned defaults follow the selected release.
- Generated Blender addon ZIP passed archive integrity and root manifest checks. Its manifest requires Blender 5.1+. First activation and socket connection remain local setup steps.
- Fixed issues found during verification: missing cross-platform npm lock entries, incompatible existing Node detection, obsolete local file URLs in Python requirements, machine-specific server paths, and installation into a previously absent custom CODEX_HOME.
- Commercial software executable paths were discovered on the test machine. No CAD/optical project operations were invoked; licenses were not checked. This is not native modeling/simulation acceptance or a test on a second physical computer.
- Credentials, account configuration, private models, databases and task history are excluded. Native logs, dependency environments and machine paths remain outside Git. Known-pattern scanning is supplemented by narrow source selection; it is not a guarantee against every possible secret format.
- Upstream generated Blender build duplicates are excluded from Git and runtime source enumeration. The release retains original license notices and upstream provenance.

Windows and Linux CI run regression, privacy and integrity checks. Linux native application operation is not claimed. Commercial apps/licenses, optional reverse-engineering engines and third-party account logins must be installed/configured on each destination computer.
