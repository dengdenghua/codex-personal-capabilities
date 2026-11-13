# Performance admission and document recycling

Use the configured Python runtime with `psutil`. These helpers do not install anything.
The admission gate is read-only and does not call COM, so it can run while CAD is busy:

```powershell
python scripts/sw_resource_guard.py --target solidworks --allow-reuse
python scripts/sw_performance.py --output performance_before.json
```

Exit 4 means **do not submit another load, rebuild or export**. Default thresholds
reserve at least 2 GiB of physical RAM, with a warning below 10%. SolidWorks private committed
memory warns at 45% and blocks new heavy work at 65% of physical RAM. On a 32 GiB
machine these are approximately 14.4/20.8 GiB; use actual reported RAM, not the label.
Working set alone is insufficient because paging can make it misleadingly small.
Thresholds are conservative local defaults, not SolidWorks capacity guarantees.
Local override recorded 2026-10-10: the user explicitly requested a looser
performance policy during the R48 harness task. The available-RAM fraction was
changed from a 15% stop to a 10% warning and a 2 GiB stop, after measured available
RAM varied from 3.86 to 2.21 GiB between checks. CAD and rendering are staggered.
The private-memory limits, serialization and document-ownership protections remain.
Adjust `MemoryPolicy` only for a measured workload/hardware reason and record it;
do not raise the limit simply to make a failed gate pass. Unknown resource readings
also block new heavy work. The gate does not interrupt an in-flight COM call.

## Ownership and checkpoints

Inside the existing serialized CAD job, record `snapshot_documents(sw)` before
opening anything. A path/name resemblance or old version is not ownership. Track
the exact paths this task opens/creates, plus which documents are still needed.
At most two independent task windows should remain: the assembly/drawing and the
one part/model required now. Its loaded dependency documents are a separate count;
closing a child window may not unload it while its parent remains open.
Before each new/open call, run `assert_task_window_budget(sw, owned_paths,
opening_path=next_absolute_path)` from `sw_document_recycler`. It reads actual
`IFrame.ModelWindows`, so an assembly's hundreds of automatically loaded components
are not mistaken for hundreds of windows. Save a new task document to its working
path and register it before starting another one; do not accumulate unnamed models.

After each useful result: finish rebuild/validation, save affected child parts and
then their assembly, verify save return codes and output files, record SHA-256, and
release no-longer-needed documents before opening the next revision. Save only
authorized working copies. Dirty historical/source/other-task models must remain
open until their unsaved state can be preserved deliberately. Never use SaveAll,
CloseAll, process termination, EmptyWorkingSet or GC alone as "memory recovery".

`sw_document_recycler.py` accepts this explicit checkpoint manifest:

```python
manifest = {
    "task_id": "current-task-identity",
    "documents": [
        {"path": absolute_working_path, "completed": True, "sha256": verified_file_hash},
        # Include owned child parts too; completion means the saved checkpoint was verified.
    ],
}
plan = recycle_completed(sw, manifest, keep=[current_required_path], dry_run=True)
# Read the plan; inside the SAME exclusive CAD job, execute authorized cleanup.
result = recycle_completed(sw, manifest, keep=[current_required_path], dry_run=False)
```

The recycler has no standalone COM connection and must share the machine-wide CAD
lock. It rechecks each parent and loaded dependency, dirty flags, ownership, saved
hashes, title uniqueness and retained references before closing. Unknown/virtual
dependencies and changed checkpoints are retained. **A clean parent with a dirty
child cannot be closed.** It never saves or discards unsaved data. If cleanup cannot
release enough capacity, stop opening more cases and explain the retained files.
Release stale Python COM references, then measure real memory again. If memory
stays above the gate, do not continue just because document count decreased.

## Final review can dirty child parts

The last export/review/rebuild is a lifecycle boundary, not merely a read-only
inspection. In a verified local run, `run_review()` left all 36 loaded working
parts dirty while the saved assembly itself was clean. The recycler correctly
retained the parent. Do not weaken that protection or discard those children.

After all required review and preview operations, inside the same serialized job:

1. Inspect fresh parent and child save flags and exact task ownership.
2. For dirty working copies, compare their geometry/appearance with the reviewed
   state. If the state changed materially, refresh the affected checks, previews
   and exports; do not reuse stale delivery evidence.
3. Save only verified task-owned working children, check each save result and
   clean flag, then save the parent. Preserve unknown or foreign dirty documents.
4. Compute final file hashes after those saves. Write the cleanup result BEFORE
   asserting it succeeded, so retained reasons survive a failed assertion.
5. Recycle from that checkpoint and measure memory again. If any later operation
   dirties a document, refresh its checkpoint rather than reusing the old hash.

## Frozen or shared sessions

Check queue status first. While another job owns the queue, collect only OS metrics
and existing evidence; do not submit extra COM probes. A long rebuild with increasing
CPU/I/O is different from no progress. If CPU/I/O and stage are unchanged across
spaced observations and the window is unresponsive, stop submitting CAD work and
inspect the visible state through supported UI tools. A timeout never means a
mutation was cancelled. A completed STEP file is not proof that SaveAs returned.

Do not kill/restart a shared session or delete its queue lock. If a restart is needed,
first preserve all affected unsaved documents, resolve other active work, and obtain
authorization for the restart. If the app cannot save, report the exact limitation;
continue only offline work on already-saved files. A completed case leaves a cleanup
record: closed paths, retained paths/reasons, open counts, and memory before/after.
Inspect the recycler's final `retained` list, including documents excluded before
any close attempt. A successful cleanup call can retain every document; it is not
proof of recovered memory. Report recovery only from the subsequent OS sample.
