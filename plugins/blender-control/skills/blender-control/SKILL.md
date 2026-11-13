---

name: blender-control

description: Control this Windows machine's Blender session through the local Blender MCP for scene inspection, object placement, mechanical assembly visualization, PCB replacement, screenshots, rendering, and exports. Use when work must read or modify a live .blend scene.

---



# Blender 本地控制



For stage-based or comprehensive smart-sleep structural reviews, start with [sleep-structural-review](../sleep-structural-review/SKILL.md). It selects the specialists by development stage and unifies issue IDs, risk reasoning, evidence and test actions.



For this user's current water-circulated sleep temperature product, select the [sleep-system review skills](references/sleep-review-index.md): prioritize hydraulics/leaks, flexible waterpad life, temperature/fault protection and condensation; add night acoustics, fluid hygiene, filling/service and contact/sensing as relevant. The existing thermal and electrical safety skills include sleep-specific supplements; do not assume AV/ICT standards apply to this product.



For structural design reviews, use the [structural review index](references/structural-review-index.md) to select stack/interference, tolerance, assembly/service, thermal/airflow or manufacturing checklists. Load only the requested topics; each separates standard applicability, engineering guidance and physical validation.



For electrical product internal-stack safety reviews involving PCB, brackets, heatsinks or wiring, also load [internal-stack-safety](../internal-stack-safety/SKILL.md). It supplies the spacing/insulation/fixing checklist and versioned clause evidence; scene geometry alone does not establish safety compliance.



Use the plugin's `blender_official` MCP tools to inspect and operate the live Blender scene. The connection requires the Blender MCP add-on to be enabled and listening on `127.0.0.1:9876`.



Before editing, read the blend-file path, scene objects, linked libraries, and missing files. Save to a new `.blend` path when the source is an imported or reference assembly, unless the user explicitly selected the current file as the working copy.



Use the summary and object-detail tools for reads. Use `execute_blender_code` only when an existing focused tool cannot perform the change. Keep scripts bounded to the requested scene operation and return concise evidence: affected object names, transforms, output paths, or counts.



For object replacement in mechanical assemblies:



1. Identify the selected source revision and its required mating components. A filename, screenshot resemblance, or higher revision number does not establish compatibility or validation. State the intended change and the functional features that must remain fixed before choosing the operation.

2. Inspect dimensions, origin, parent, collection, and world transform. Preserve the assembly datum, not blindly the transform numbers: assembly-coordinate meshes must not receive the placement twice; local-coordinate meshes require their placement. Keep replaced geometry hidden for recovery when practical.

3. For geometry/placement changes or previously unverified replacement parts, read [修改与替换的验证](../mechanical-stack-review/references/change-verification.md). Check the changed boundary and affected mating chain, including supports and fasteners. Unchanged transforms, valid solids, and successful imports are not assembly acceptance.

4. Inspect the affected interfaces in close-up and an overall view, then save and reopen/inspect the result. Report separately what was changed, what was measured, and what remains unresolved. A requested filename such as “正式版 V01” is honored without promoting the engineering validation state. Pure visibility changes or renames do not require a new full mechanical audit.



For PCB and connector work, distinguish appearance models from manufacturing CAD. Photographs can guide visible placement and orientation, but cannot prove hidden pin geometry, exact board dimensions, or electrical connectivity. Record assumptions in object names or a nearby text object only when useful to the project.



Prefer STEP or native CAD for dimension-critical exchange with SolidWorks. Use GLB/GLTF for visual materials and Blender exchange, and STL only for mesh or printing needs. Verify the created file exists and reopen or inspect it when the export is a deliverable.



Do not run unrelated Python, install packages from scene scripts, or write outside the requested project and explicit output paths. Avoid global destructive cleanup commands. When many objects are changed, save a new checkpoint before the mutation.
