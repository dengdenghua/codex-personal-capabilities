---
name: solidworks-agentic-automation
description: "Agent-oriented SolidWorks automation for Windows using Python COM. Use it to create or edit parts, build real mated assemblies, export CAD, review previews, recover from COM failures, and record reproducible evidence while enforcing a single heavyweight CAD/CAE instance."
---

# SolidWorks Agentic Automation

## This Windows installation

Read [references/local-runtime.md](references/local-runtime.md) for the configured
Python executable, tested SOLIDWORKS version, output directory, and verified plate
generator. Use that interpreter instead of the Windows Store `python.exe` alias.

Use this skill when an agent must operate SolidWorks as a tool, not merely write a macro.
The required result is a reproducible CAD artifact plus evidence that it was rebuilt,
saved, exported, and visually reviewed.

This is a reusable orchestration pattern, not a domain model. Keep project-specific
geometry, dimensions, materials, loads, optimization objectives, and solver adapters in
a sibling domain adapter. See `docs/domain-adapters.md` and
`templates/domain-adapter/`.

## Capability gate

Before claiming that SolidWorks was controlled or that any artifact was created, prove
that the current runtime can:

- execute a real local shell and Python process;
- access the requested Windows output directory;
- import the required COM dependencies; and
- connect to `SldWorks.Application` in the same interactive Windows session as
  SolidWorks.

Run `python scripts/sw_preflight.py --no-install` and inspect its actual output. If the
runtime cannot execute the command, cannot reach the user's filesystem, or cannot access
the SolidWorks COM session, stop and state that the current environment can only provide
instructions or source code. Uploading this repository as chat knowledge does not grant
local shell, filesystem, COM, or desktop access.

Never claim that a file was generated, verified, attached, uploaded, or made downloadable
unless a tool actually created it and the agent inspected its absolute path, size, and
modification time. Do not present plain text as a download link, invent an attachment, or
direct the user to search a chat library for an artifact that the current runtime did not
attach. Keep the requested filename consistent from creation through delivery.

## Operating contract

Before changing CAD, establish:

- source model and whether it may be modified; default to a working copy;
- geometric invariants, interfaces, units, tolerances, and material assumptions;
- expected outputs such as `.SLDPRT`, `.SLDASM`, STEP, STL, drawings, or previews;
- acceptance checks, including body count, rebuild errors, mates, interference, and envelope;
- unknown values, recorded as `null` instead of guessed dimensions.

Never overwrite the user's only source model. Keep source, generated CAD, exports,
previews, and evidence reports as separate artifacts.

## Mechanical engineering delivery requirements

For mechanical design, optimization, manufacturing drawings and release reviews,
read [references/mechanical-engineering-delivery.md](references/mechanical-engineering-delivery.md)
and apply its requirements to the changed features and affected interfaces. Cover
datums, parameter relationships, tolerances, manufacturability, assembly/service,
fasteners/seals, materials, structural verification, inspection and revision consistency.
Select checks by process, function and risk; do not turn a local edit into unrelated
redesign or require every analysis for every part. Record applicable checks as passed,
failed or unverified, with evidence; identify not-applicable items when material to
the review. Geometry success alone must not be presented as manufacturing, functional
or production approval. Continue authorized work while clearly tracking open items.

## Agent loop

When modifying geometry, replacing historical parts or moving assembly components,
read [修改正确性检查](references/change-verification.md). Establish functional acceptance
before the modeling operation, then verify actual geometric differences and dependent
interfaces. Body validity, rebuild success and preserved coordinates are necessary
evidence for their own checks, not proof that the requested modification is correct.
Pure visibility, rename and save-copy requests retain their limited scope.

1. Run `python scripts/sw_resource_guard.py --target solidworks --allow-reuse`
   BEFORE COM preflight. A blocked memory gate means no new load/rebuild/export.
2. Read [references/performance-recycling.md](references/performance-recycling.md)
   for document ownership, checkpoint cleanup and limits. Run COM preflight only
   once the resource gate passes and no other serialized CAD job is running.
3. Convert the request into explicit inputs, constraints, outputs, and checks.
4. Prefer deterministic Python helpers in `scripts/` over generated VBA.
5. Execute one small modeling stage at a time and check every COM return value.
6. Rebuild, save, export, and run `sw_review.run_review()`. After the LAST review or
   rebuild, inspect the save flags again: review can dirty referenced parts. Verify
   and save affected task-owned working children, then their assembly, and only
   then record the final checkpoint hashes. Follow the post-review sequence in
   [performance-recycling.md](references/performance-recycling.md).
7. Inspect preview images. Rule-based review cannot prove geometric intent.
   After the document's required checks are complete, close it before opening the
   next independent part or drawing; follow the document cleanup rules below.
8. If a step fails, classify it before retrying: environment, selection, geometry,
   rebuild, export, path/encoding, dialog, timeout, or resource conflict.
9. Change one variable, retry from the earliest uncertain stage, and record the event.
10. Finish only when required artifacts and acceptance evidence exist, and report their
    verified absolute paths, sizes, and modification times.

## Appearance and comparison evidence

- A successful material setter or matching property readback is not proof of the
  displayed result. Check part/face and assembly overrides, capture the actual
  native view, and verify persistence after saving and reopening the candidate.
  Some body-level setters preserve existing lighting values even when RGB changes;
  record the actual supported values instead of repeatedly issuing the same write.
- Label every presented screenshot with **revision, view and status**, for example
  `R16 | exhaust side | candidate`. Keep that identity in its filename and adjacent
  caption; comparison pages should also show it over or above each image. Default
  to older/baseline on the left and newer/candidate on the right. Distinguish trial
  branches from the selected deliverable, and retire stale "latest" labels.
- Judge visual changes from the saved native model. Appearance-rule checks and
  numeric CAD review scores are not aesthetic scores. A finish proposal does not
  validate its physical coating process, gloss or thermal effect.

Use `scripts/sw_evidence.py` for atomic JSON evidence and
`scripts/sw_agent_loop.py` for workflow state transitions. See
`docs/agent-loop.md` for the full state machine.

## Core modules

| Need | Module |
|---|---|
| Environment and COM checks | `scripts/sw_preflight.py` |
| Single-instance CAD/CAE guard | `scripts/sw_resource_guard.py` |
| Connection and document lifecycle | `scripts/sw_connect.py`, `scripts/sw_session.py` |
| Sketches and part features | `scripts/sw_part.py` |
| Components and real mates | `scripts/sw_assembly.py` |
| Appearance and material display | `scripts/sw_appearance.py` |
| Drawings | `scripts/sw_drawing.py` |
| STEP/STL/IGES/PDF/DXF export | `scripts/sw_export.py` |
| Multi-view preview and review report | `scripts/sw_review.py` |
| Structured evidence | `scripts/sw_evidence.py` |
| Guarded generated VBA | `scripts/sw_macro_guard.py` |

## Minimal part workflow

```python
import sys
sys.path.insert(0, r"PATH_TO_SKILL/scripts")

from sw_connect import mm, rebuild_document
from sw_part import sketch, sketch_circle, extrude_boss
from sw_review import run_review
from sw_session import SolidWorksSession

session = SolidWorksSession()
model = session.new_part()

with sketch(model, "Front Plane") as sketch_name:
    sketch_circle(model, 0, 0, mm(25))

feature = extrude_boss(model, sketch_name, mm(50))
if feature is None:
    raise RuntimeError("Boss extrusion returned None")

rebuild_document(model)
session.save(model, r"<LOCAL_PATH>")
session.export(model, r"<LOCAL_PATH>")
report, report_path = run_review(
    model,
    r"<LOCAL_PATH>",
    basename="cylinder",
    expected_outputs=[
        r"<LOCAL_PATH>",
        r"<LOCAL_PATH>",
    ],
)
if report["evaluation"]["status"] == "fail":
    raise RuntimeError(f"CAD review failed: {report_path}")
```

Replace `PATH_TO_SKILL` with the installed skill directory. SolidWorks API lengths
are meters; use `mm()` and `deg()` at the boundary.

## Part modeling rules

- Native feature sketches must have intentional geometric constraints and editable
  driving dimensions. Use appropriate coincident, horizontal/vertical, tangent,
  concentric, equal and symmetry relations to express design intent; dimension size
  and location against stable datums. Coordinates used to draw geometry are not
  constraints, and dimension-like text or reference dimensions are not driving
  parameters.
- Check each new or modified feature sketch with `GetConstrainedStatus` and require
  fully defined status before treating it as complete. Resolve under-defined,
  over-defined or conflicting geometry before saving the deliverable. If the user
  explicitly needs an intentionally movable sketch, identify its remaining degrees
  of freedom and purpose rather than claiming it is fully defined.
- Do not fix every entity or freeze an entire sketch merely to obtain fully defined
  status. A fixed datum point is acceptable; functional geometry must retain useful
  dimension-driven editing. Automatic dimensioning is only a starting point: inspect
  the resulting relations and dimensions for the intended design behavior.
- Give feature/sketch names and key driving dimensions meaningful names, keep size
  and position dimensions readable in sketch-edit mode, and expose shared parameters
  through equations where linked features must change together. After a representative
  parameter change, rebuild, verify the intended geometric change, restore the nominal
  value and save; record sketch constraint status and the edit check as evidence.
- Store the returned feature or `ActiveSketch.Name`; do not guess localized names.
- Select the exact profile or returned feature object before creating dependent features.
- Treat `None`, `False`, a nonzero error code, unexpected suppression, or unexpected
  body count as failure even if a STEP file was written.
- For edits to historical feature trees, preserve dimension identity until its geometric
  meaning is verified in the UI.
- Use `rebuild_document(model)` because some dynamic COM wrappers expose
  `EditRebuild3` as a property instead of a callable method.
- After every topology change, check rebuild status, body count, envelope, interfaces,
  output timestamp, output size, and previews.
- See `references/part-modeling.md` and `references/troubleshooting.md`.

## Assembly rules

- `AddComponent4(x, y, z)` is only an initial placement. It does not create an assembly.
- Fix one datum component, then add engineering mates to the remaining components.
- A coaxial stepped interface normally needs a concentric cylindrical mate and a
  coincident planar mate. Lock concentric rotation when required.
- Accept `AddMate5` only when the returned mate is non-null and its by-ref error status
  reports success.
- Verify final transforms, analytical gaps, degrees of freedom, interference, rebuild,
  STEP export, and assembly previews.
- If an expensive interference scan is skipped, record `skipped=true` and the reason;
  never report a skipped scan as zero interference.
- See `references/assembly.md`.

## Resource guard

Performance recycling is required before opening another independent document,
before heavy rebuild/export, and after a completed case. Use the read-only memory
gate and scoped recycler in [references/performance-recycling.md](references/performance-recycling.md).
Keep at most two task-owned independent document windows (one assembly/drawing and
the part/model currently needed); loaded assembly dependencies are not extra windows.
Compare revisions sequentially through saved previews, closing the previous assembly
first. Record a before/after document inventory and memory sample for each batch.
Do not treat a clean assembly save flag as proof its child parts are saved.

- Never launch multiple SolidWorks application instances for batch work.
- Never run SolidWorks and ANSYS/Mechanical simultaneously on a memory-limited machine.
- Reuse the active SolidWorks instance when it belongs to the current job.
- Generate CAD cases sequentially. Close documents and exit SolidWorks before a large
  CAE solve unless the user explicitly needs it kept open.
- Inspect process state, logs, and visible dialogs before declaring a long rebuild stuck.
- Do not terminate processes owned by another task automatically.

### Close unused document windows promptly (required)

- A single SolidWorks instance can still exhaust memory with dozens of open parts
  and drawings. Do not accumulate completed documents or wait until the end of a
  batch to close them. Hiding or minimizing a window is not document cleanup.
- Keep only the document being edited and documents needed for the current
  operation. For drawing work, normally keep only the current drawing and its
  referenced model; for assembly work, retain the active assembly and necessary
  dependencies, without opening every component in a separate window.
- Save and verify the native file, finish required exports, previews and reopen
  checks, then close the completed document immediately. Close each finished
  drawing before starting the next one. Preserve the model's saved path for later
  reopening instead of keeping it open just in case.
- Track documents opened or created by the current task. Before opening the next
  independent document, inspect the open-document list and close task-owned items
  that are no longer needed. Use the verified document identity with `CloseDoc`;
  do not use a blanket close-all operation in a shared session. Release stale COM
  references after closing. Assembly-referenced models may remain loaded even
  after their separate windows close; close the owning assembly when finished.
- Put cleanup in batch scripts' `try/finally` paths so failed attempts and scratch
  documents do not accumulate. Save useful task-owned unsaved work to a recovery
  copy before closing; discard only known disposable task-created scratch work.
  If saving fails, preserve that document and resolve the failure before opening
  more cases. Never silently discard unknown unsaved work or close another task's
  active documents.
- At completion or CAD handoff, close unused task-owned documents. Leave only the
  result currently needed for user viewing or the next operation, and identify any
  documents intentionally retained because of unsaved work or active references.

## Failure recovery

- Prefer a saved UTF-8 `.py` file over long inline PowerShell when paths are non-ASCII.
- Log selected entity count, type, coordinates, selection mark, feature return value,
  error code, body count, and output file metadata.
- Probe uncertain COM methods in a minimal script and verify the official SolidWorks API
  signature before integrating them into a large workflow.
- For optional arrays and by-ref values, use explicit COM `VARIANT` types.
- If geometry fails repeatedly, simplify or split the local feature while preserving
  overlap and design intent. Do not relaunch the same invalid geometry indefinitely.
- A busy SolidWorks process with increasing CPU may still be rebuilding. Check for modal
  dialogs and evidence of progress before recovery.
- See `docs/com-survival-guide.md` and `references/troubleshooting.md`.

## Generated macro policy

Python COM helpers are the default. If generated VBA is necessary, pass it through
`sw_macro_guard.validate_vba_macro()` and use bounded retries. A local deterministic
template may be used only when it represents the requested geometry; never report the
fallback as the requested model without review.

## Completion evidence

A successful run should include:

- source provenance and requested constraints;
- generated native CAD and requested neutral exports;
- rebuild and feature checks;
- body/component count and assembly mate checks where applicable;
- output timestamps and sizes;
- isometric plus orthographic previews;
- structured event/evidence JSON;
- applicable mechanical engineering checks, affected-document revision status and
  the supported delivery stage, as defined in the mechanical engineering reference;
- explicit manual visual-review result and any residual uncertainty.

Run `python scripts/validate_skill.py` before sharing or publishing the skill.
