---

name: kicad-automation

description: Create, inspect, and edit KiCad schematics and PCBs on this Windows machine using official Python IPC, a local MCP, schematic file APIs, and KiCad CLI. Use for KiCad circuit design, layout, ERC/DRC, Gerber/drill and STEP exports.

---



# KiCad automation



## Local runtime



- KiCad 10.0.6: `<LOCAL_PATH: configure on this computer>`.

- CLI: `<LOCAL_PATH: configure on this computer>`.

- Automation Python: `<LOCAL_PATH: configure on this computer>`.

- MCP server: `<LOCAL_PATH: configure on this computer>`; Codex server name `kicad`.

- Symbols and footprints: `<LOCAL_PATH: configure on this computer>`.

- Set `KICAD_SYMBOL_DIR` to its `symbols` directory before importing `kicad_sch_api`.

- Verification evidence and runnable sample: `<LOCAL_PATH: configure on this computer>` and `test-project/`.



## Workflow



1. Identify the intended project, revision, supply voltages, interfaces, part ratings, board outline, mounting holes and manufacturing rules. Inspect existing files before changing a design. Derive mechanical constraints from the actual CAD/export when supplied.

2. Preserve original files and work on a named project copy for substantial edits. Keep schematic reference designators, footprint library identifiers, pin numbers and network names consistent.

3. Prefer official `kipy.KiCad()` for the running PCB editor. IPC is enabled locally; open the intended `.kicad_pcb` first. Read its project directory and board name before writing. Reacquire objects after updates. Use commit/update/push for undoable edits and save explicitly.

4. For schematics, use `kicad_sch_api` on saved files. The local MCP supports inspection and value changes to new files; it does not provide live schematic IPC. Never overwrite a file while its editor holds unsaved changes. Inspect actual library pins and use 1.27 mm grid where appropriate.

5. For new boards, load real library footprints. Do not represent a library footprint with an empty object. The bundled KiCad Python/pcbnew bootstrap is available for offline construction, but is a legacy API and must not modify an open board file. Sample builders demonstrate this separation.

6. Validate electrical choices and pin mapping, then route against actual net assignments, widths, clearances and stackup. Moving footprints through the MCP does not reroute attached tracks. A clean geometry check alone is not proof of correct electronics.

7. Save, run ERC and DRC including schematic parity, inspect the rendered schematic/layout, and export from the final saved revision. Report remaining warnings explicitly; do not suppress checks to obtain a pass.



## Tested MCP tools



`connect_kicad`, `get_board_info`, `list_footprints`, `set_footprint_value`, `move_footprint`, `add_board_text`, `save_board`, `inspect_schematic`, `set_schematic_value`.

Positions are mm. PCB and schematic value changes are separate operations. This is a small local adapter using official IPC, not a full autorouter. Other functions require direct official API/CLI work and validation before claiming support. The downloaded daedalus/mcp-kicad source is reference-only: its connection API was incompatible with kicad-python 0.8.0 and it is not registered as another server.



## Validation and exports



Run the CLI with an argument array or properly quoted PowerShell paths; first inspect `--help` if changing flags.



- `sch erc --format json --exit-code-violations -o <erc.json> <project.kicad_sch>`

- `pcb drc --schematic-parity --format json --exit-code-violations -o <drc.json> <project.kicad_pcb>`

- `sch export netlist --format kicadxml -o <net.xml> <project.kicad_sch>`

- `sch export pdf -o <schematic.pdf> <project.kicad_sch>`

- `pcb export gerbers -o <output-directory> <project.kicad_pcb>`

- `pcb export drill -o <output-directory> <project.kicad_pcb>`

- `pcb export step -o <model.step> <project.kicad_pcb>`



Local labels appear as `/NAME` in the netlist; preserve that exact name on the PCB. Preserve full footprint identifiers such as `Resistor_THT:R_Axial_...`. Check zero unconnected items and zero schematic parity issues separately from DRC violations. Default checks can be ignored by KiCad; examine report `ignored_checks` and apply fabrication rules for real designs.



## Recovery



If MCP tools are absent from a conversation, use the same Python runtime directly; a new Codex session may be needed to load saved MCP/skill configuration. If IPC fails, check that PCB editor is running and Preferences > Plugins > Enable IPC API Server is enabled. Do not replace or restart an unrelated open project. Package versions are recorded in `<LOCAL_PATH: configure on this computer>`.
