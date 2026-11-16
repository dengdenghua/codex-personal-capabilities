# Verification — v1.3.2

Full private cloud recovery acceptance (2026-11-16):

- The authorized full encrypted backup was independently read back through Quark's official CLI. Every ciphertext object matched its SHA256, the entire restic repository passed `check --read-data`, and the complete decrypted archive matched the original SHA256 and length.
- The cloud-origin archive restored every available archived file into a new directory. Every restored file passed SHA256 validation; all four SQLite databases passed integrity and table-count checks. Historical originals already absent from the source remain explicitly listed as missing, with the operator's accepted incomplete-source status preserved.
- A fresh GitHub checkout installed the optical plugins and personal helpers in an isolated Codex home. Both the runtime and installed plugin launcher passed real Chinese retrieval, reference readback, graph and workflow memory queries, lens prescription/source verification and project inventory. Additional checks required source resolution to stay inside the newly restored tree, preventing old machine paths from satisfying acceptance accidentally.
- This was a full local simulation of migration using independently downloaded cloud data, not a test on a second physical computer. Active Codex configuration was not changed; native commercial application operation and licenses were not tested.
- A compressed recovery attempt correctly stopped at the disk reserve boundary. After fingerprint-verified duplicate retirement and local storage relocation, full recovery passed on a volume with sufficient uncompressed capacity. The canonical local archive retains the exact original bytes; the retained copy was independently decrypted from Quark. Private transfer identifiers, source paths, data inventories and raw logs remain local.
- Fixes cover stalled CLI downloads with bounded retries, repeated progress heartbeats, optional worker limits, and rebinding the authenticated local mirror after migration so subsequent incremental backups succeed without the old machine path.
- Windows CI at d21a3c2 passed 66 portable/cloud tests plus 112 optical workbench tests. Linux ran the same suites with one Windows-only compression test skipped: 65 plus 112 passed. Both passed source/privacy/tracked-hash validation. Cloud protocol fixtures in CI are synthetic; the private full-cloud acceptance above is a separate real-account test.
- No unlock secret, recovery record, cloud credentials or private source data was published; no public cloud share was created. The public release contains generic source, documentation and synthetic tests only.

Retained v1.3.1 acceptance:

Recovery follow-up (2026-11-15):

- Windows CI passed 63 portable/cloud tests and 112 optical workbench tests. Linux CI passed the same suites with the Windows-only compression case skipped (62 + 112 passed). Both platforms passed source/privacy/tracked-hash checks at commit b07847f.
- Follow-up covers unfinished SHA256 readback resume, worker bounds, bounded API-timeout retry, Windows NTFS compressed restore, cross-volume cache handling, and exclusion of local readback receipts from ciphertext upload. At that release, full private cloud recovery was pending; it is covered by the separate v1.3.2 acceptance above. Small-fixture passes alone do not substitute for it.

Cloud extension, retained v1.3.0 evidence (2026-11-15):

- Windows and Linux CI: 59 portable/cloud tests and 112 optical workbench tests passed (171 per platform), including real pinned encryption/transport tools. Quark protocol fixtures are explicitly synthetic.
- Pinned official restic 0.19.1 and rclone 1.76.0 executables, verified against fixed upstream SHA256 values, with separate local tool storage.
- A full existing private archive was encrypted locally and completely decrypted/read back to its original SHA256 without uploading its unlock secret. The existing missing-originals status is preserved.
- New tests cover real encryption/SQLite recovery, wrong keys, authenticated corruption detection, interrupted download repair, hardlink and existing-data protection, local secret permissions, upload boundaries, and the real rclone transport against a local fixture. Local transport tests are explicitly labeled as tests, never live cloud backups.
- Quark's official installed CLI was tested against a real authorized account: a synthetic encrypted sample uploaded, every encrypted object was read back, the archive decrypted to its original SHA256, and Restore-Cloud.ps1 restored its source file into a fresh directory. A second recovery succeeded with the original local mirror path unavailable, reusing confirmed cloud downloads and retrying a TLS-interrupted object. No public sharing link was created. The full private archive is a separate live transfer and is not claimed complete by this small-sample acceptance.
- Quark recovery tests use synthetic cloud objects plus real restic encryption. They cover transfer checkpoints, altered ciphertext, local path/hardlink protection, restoration after removal of the original mirror, fresh cloud verification despite an existing cache, and preservation of the current recovery record when an update fails.
- Network retries preserve confirmed objects and do not blindly retry authorization or unsupported-command errors. A subsequent snapshot reuses unchanged immutable cloud objects and retains the preceding recovery record.
- Public code does not contain the ciphertext repository, recovery file, cloud login configuration, plaintext data, or unlock secret. Restic's standard encrypted key envelopes are part of the encrypted repository; the usable unlock secret remains local.
- Verification checks all encrypted packs without using a metadata cache before decrypting and hashing the archive. This also detects corruption in sidecar packs that the selected archive alone would not read.

Retained optical/runtime acceptance from v1.2.0:

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
