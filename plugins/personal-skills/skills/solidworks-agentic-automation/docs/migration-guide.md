# Migration Guide

## 1. Copy or clone the skill

Place the repository where the target agent discovers skills, or add `scripts/` to
`sys.path`. Do not copy local `output/`, CAD files, evidence, or private project adapters.

## 2. Validate the target computer

```powershell
python -m pip install -r requirements.txt
python scripts/sw_preflight.py --no-install
python scripts/sw_resource_guard.py --target solidworks --allow-reuse
python scripts/validate_skill.py
python -m pytest
```

Confirm the SolidWorks version, UI language, part/assembly/drawing templates, license,
and whether the agent can inspect screenshots or generated previews.

## 3. Run the generic smoke test

With one SolidWorks instance available:

```powershell
python examples/agent_loop/build_mounting_plate.py --output-dir <LOCAL_PATH>
```

Open the native part and STEP, then inspect the review images and `evidence.json`. A clean
smoke test proves the local COM path; it does not validate a domain-specific generator.

To verify component insertion and real mates, run:

```powershell
python examples/agent_loop/build_mated_assembly.py --output-dir <LOCAL_PATH>
```

## 4. Add a project adapter

Create a separate repository or sibling directory containing:

- domain input schema and examples;
- project-specific geometry generators;
- named invariants and tolerances;
- optional CAE adapter and solver evidence;
- private CAD and results ignored by Git.

Import the shared modules from this repository. Do not place confidential model dimensions
or experiment data in the reusable Skill.

## 5. Revalidate after upgrades

Run the smoke test after changing SolidWorks, Python, pywin32, templates, UI language, or
GPU/driver settings. Record version data in each production evidence report.
