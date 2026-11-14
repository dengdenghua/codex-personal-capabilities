# Verification — v1.2.0

2026-11-15, Windows x64:

- 11 plugin packages / 82 SKILL.md entries. All 144 automated tests passed: 32 portable installation/recovery tests and 112 optical workbench tests. Test data in Git is synthetic.
- Source/privacy checks, plugin manifests and the SHA256 inventory are validated before publication. SQLite databases, original documents, models, memory records, private plans, restoration mappings and acceptance logs remain outside Git.
- Installed Python dependencies into isolated per-service virtual environments; each passed pip check. REA installed with npm ci from the repaired cross-platform lock file, using Node 24.22.1 verified against nodejs.org SHA256.
- The Install.ps1 entry point installed all 11 packages through the official Codex CLI in a fresh, separate CODEX_HOME. Active Codex configuration was not modified.
- All seven managed MCP runtimes passed real initialize / tools/list checks. The six native plugin launchers were also verified in v1.1.1:

| Service | Tools returned |
|---|---:|
| Optics Workbench | 40 |
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
- Optical recovery tests cover SQLite WAL snapshots, relocated paths, database integrity and table counts, archive corruption, path traversal, refusal to overwrite existing data, explicit handling of missing originals, source mutations, preservation of historical identities, installation retry, and meaningful configuration rollback. Multiple historical versions of the same path are resolved by SHA256.
- The optics service needs only Python's standard library. Standalone workflow memories remain separate from graph memories; recovery does not assert that they have been synchronized.
- A real private dataset was independently restored through Install.ps1 from a fresh GitHub checkout. Every restored file passed SHA256 verification, and all four SQLite snapshots passed integrity and table-count checks. Both the direct runtime and installed optics plugin launcher passed Chinese retrieval, reference readback, graph/memory queries, lens prescription detail, source identity and saved-project checks. Historical originals already absent from the source machine remain explicitly listed as missing; the operator accepted recovery of available data. This is not a claim that every historical original was recovered.
- All three packaged lens helpers are covered by the relocated-profile and historical-version regression, so both the dedicated lens plugin and the personal skill collection use the restored library.
- The archive tool never calls Git or the network. See [OPTICS.md](OPTICS.md) for private restoration and its explicit missing-source behavior.

Windows and Linux CI run both test suites and tracked-file privacy/integrity checks. Linux native application operation is not claimed. Commercial apps/licenses, optional reverse-engineering engines and third-party account logins must be installed/configured on each destination computer.
