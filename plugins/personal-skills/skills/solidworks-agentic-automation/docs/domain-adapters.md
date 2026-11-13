# Domain Adapters

The reusable core stops at the SolidWorks boundary. A domain adapter translates a
project request into explicit CAD inputs, constraints, geometry operations, and
acceptance checks without changing the core COM helpers.

## The adapter contract

Every adapter should make these five objects explicit:

1. **Request**: source model, units, dimensions, configurations, and unknowns.
2. **Constraints**: interface dimensions, tolerances, body count, material assumptions,
   and forbidden changes.
3. **Plan**: deterministic modeling steps and the expected feature or component handoff.
4. **Artifacts**: native CAD, neutral exports, previews, and evidence JSON.
5. **Acceptance**: rebuild status, geometry invariants, assembly mates, interference,
   and human visual review.

Unknown values stay `null`. A proposed assumption belongs in a separate `assumptions`
field and must never be silently promoted to a confirmed input.

## Recommended layout

Copy `templates/domain-adapter/` into a separate project or repository:

```text
my-domain-adapter/
  adapter.yaml              # project inputs and acceptance contract
  adapter.py                # domain orchestration; imports the core skill
  README.md                 # project-specific setup and known limitations
  cad/                      # private native CAD and generated workspaces
  evidence/                 # private run evidence and previews
```

Keep the adapter outside this repository when it contains proprietary geometry,
experiment data, supplier information, or solver results. The adapter may import the
core scripts by path or install the repository as a local package.

## Execution boundary

The agent may decide *what* should be built and *which* adapter operation to call. The
adapter owns deterministic geometry and file handling. The core skill owns COM session
lifecycle, resource guarding, rebuild/export checks, review, and evidence. This split
makes the same workflow useful for brackets, fixtures, housings, gears, robot links,
and other mechanical parts.

Do not put ANSYS, SolidWorks Simulation, material databases, or a project-specific
optimization objective into the generic core. Add them as a separate CAE adapter and
record solver/license/contact/mesh assumptions in its evidence.

## Adding a new operation

1. Define the request and acceptance contract in `adapter.yaml`.
2. Implement one deterministic operation in `adapter.py`.
3. Use returned COM objects and explicit units; do not guess localized feature names.
4. Rebuild, save, export, and run `sw_review.run_review()`.
5. Record the operation and artifact checks with `EvidenceRecorder`.
6. Add an offline test for the contract or parser before running SolidWorks.
7. Run a one-instance SolidWorks smoke test and inspect the generated previews.

The template intentionally refuses to claim that a domain model passed until the domain
adapter supplies its own geometry implementation and acceptance checks.
