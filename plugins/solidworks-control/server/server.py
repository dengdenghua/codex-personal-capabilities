from mcp.server.fastmcp import FastMCP
from jobs import submit,status,health,acknowledge
from typing import Literal
mcp=FastMCP('SolidWorks Local Control',instructions='All CAD commands return a job_id. Poll sw_job_status until completed. Submission is not success. Legacy commands serialize machine-wide. Opt-in sw_parallel tools bind explicit PID/creation-time sessions with exclusive workspaces, serialize within each instance, and may overlap across two instances. The parallel pool blocks legacy operations until released. Never retry a mutation automatically after a failure or timeout. Use exact document identities; source files are not overwritten. No tool force-terminates SolidWorks. Parallel release may normally exit only its own empty process. Existing custom scripts retain the legacy queue unless explicitly migrated.')
@mcp.tool()
def sw_health()->dict:
    """Read SW/import processes and active job without calling COM; works during long imports."""
    return health()
@mcp.tool()
def sw_start()->dict:
    """Explicitly start SW only if absent, otherwise reuse its one existing instance."""
    return submit('start',{})
@mcp.tool()
def sw_session()->dict:
    """List actual open document paths/titles, active document, revision and template health."""
    return submit('session',{})
@mcp.tool()
def sw_open(path:str,read_only:bool=True)->dict:
    """Open one native CAD file or import one STEP/IGES/Parasolid. Native files default read-only. STEP uses restored import settings and keeps multibodies in one part."""
    return submit('open',dict(path=path,read_only=read_only))
@mcp.tool()
def sw_inspect(document:str)->dict:
    """Read document features and solid bounds, with explicit limits; requires exact path/title."""
    return submit('inspect',dict(document=document))
@mcp.tool()
def sw_components(document:str)->dict:
    """Read assembly top-level component names, reference paths, suppression and transforms."""
    return submit('components',dict(document=document))
@mcp.tool()
def sw_externalize_virtual_copy(document:str,output_directory:str)->dict:
    """Create a NEW assembly preparation copy and externalize its owned embedded parts/subassemblies recursively. Source must be saved and clean. Does not modify linked external assemblies or resolve unavailable virtual models. Reports remaining virtuals, source hashes/identities, transforms and mates. Complete flag covers virtual preparation only, NOT an independent package; follow with dependency packaging and reopen validation. Never retry blindly after partial failure."""
    return submit('externalize_virtual_copy',dict(document=document,output_directory=output_directory))
@mcp.tool()
def sw_virtual_components(document:str)->dict:
    """Read virtual and virtual-path candidate components, suppression, live model availability and solid count. Does not resolve suppressed components, externalize or save. A stale temp path does not prove missing embedded data."""
    return submit('virtual_components',dict(document=document))
@mcp.tool()
def sw_copy_dependency_package(document:str,output_directory:str,reference_remap:dict[str,str]|None=None)->dict:
    """Copy saved native CAD reference graph to a NEW folder and retarget references. Optional explicit reference_remap maps missing old paths to verified existing same-filename files; never infer versions. Includes in-context backlinks; aborts before copying unresolved/virtual paths. Hash-checks originals and every copied graph edge. DISK state only, not unsaved edits or simulation sidecars. Open/rebuild separately."""
    return submit('copy_dependency_package',dict(document=document,output_directory=output_directory,reference_remap=reference_remap))
@mcp.tool()
def sw_replace_component_copy(document:str,component_name:str,expected_path:str,replacement_path:str,output_path:str)->dict:
    """Replace exactly one named top-level component in a NEW distinctly named assembly copy, requesting mate reattachment. Requires expected old reference and native replacement. Verifies reference, transform, mate counts/errors, rebuild, source file and interference. Does not infer placement or fix incompatible mates. Copy retains other source dependencies; not Pack and Go. Unsaved source state is copied, never discarded."""
    return submit('replace_component_copy',dict(document=document,component_name=component_name,expected_path=expected_path,replacement_path=replacement_path,output_path=output_path))
@mcp.tool()
def sw_mate_status(document:str)->dict:
    """Read assembly mate feature names/types and error codes. Missing/unreadable errors are explicit; zero error does not prove design intent."""
    return submit('mate_status',dict(document=document))
@mcp.tool()
def sw_interference(document:str)->dict:
    """Check overlapping volumes in an exact assembly, including hidden bodies and ignored interferences. Lists excluded suppressed components; refuses unresolved active components. Restores detection settings, does not save or repair mates. Review intentional fits separately."""
    return submit('interference',dict(document=document))
@mcp.tool()
def sw_activate(document:str)->dict:
    """Bring an exactly identified open document to the front."""
    return submit('activate',dict(document=document))
@mcp.tool()
def sw_view(document:str,output_path:str,view:Literal['isometric','front','back','left','right','top','bottom']='isometric')->dict:
    """Set standard view and fit model, save a new BMP preview to an absolute path. Does not save source model."""
    return submit('view',dict(document=document,output_path=output_path,view=view))
@mcp.tool()
def sw_save_copy(document:str,output_path:str)->dict:
    """Save a native copy or STEP/Parasolid/STL export to a NEW path. Assembly copy retains original dependencies; it is not Pack and Go."""
    return submit('save_copy',dict(document=document,output_path=output_path))
@mcp.tool()
def sw_close_clean(document:str)->dict:
    """Close only an explicitly identified document with no unsaved changes. Never discard changes."""
    return submit('close_clean',dict(document=document))
@mcp.tool()
def sw_repair_templates()->dict:
    """Repair missing default part/assembly template paths using verified local templates; record previous values."""
    return submit('repair_templates',{})
@mcp.tool()
def sw_create_cylinder(radius_mm:float,height_mm:float,output_path:str)->dict:
    """Create a NEW test cylinder part, verify one solid and analytical volume, save to a new SLDPRT. Does not modify an existing part."""
    return submit('create_cylinder',dict(radius_mm=radius_mm,height_mm=height_mm,output_path=output_path))
@mcp.tool()
def sw_flow_feature_editor(document:str,project_name:str,kind:Literal['volume_source','global_goal','volume_goal'])->dict:
    """Open an allowlisted Flow heat-source or goal editor for the exact active project. UI invocation only: feature_created=false until the user/agent completes and verifies the UI. Does not select geometry, assign power, save or solve. Inspect any existing editor before calling; never retry blindly."""
    return submit('flow_feature_editor',dict(document=document,project_name=project_name,kind=kind))
@mcp.tool()
def sw_flow_new_project_wizard(document:str)->dict:
    """Open the installed Flow new-project wizard for an exact saved native part/assembly. Requires a healthy loaded Flow API. Finish the UI using observed controls, save and verify via project/snapshot. Invocation is not project creation or a solve; no guessed physics or automatic retries."""
    return submit('flow_new_project_wizard',dict(document=document))
@mcp.tool()
def sw_flow_diagnostics(load:bool=False)->dict:
    """Check Flow files, optional add-in loading, and API access in the serialized queue. Does NOT verify solver or Electronics/HVAC licenses. Default does not load the add-in."""
    return submit('flow_diagnostics',dict(load=load))
@mcp.tool()
def sw_flow_example(output_directory:str)->dict:
    """Copy and open the official conjugate heat-transfer example in a NEW absolute directory. Check reference isolation and presence of a Flow project. Does not solve or verify licensing."""
    return submit('flow_example',dict(output_directory=output_directory))
@mcp.tool()
def sw_flow_project(document:str)->dict:
    """Read the active Flow project for an exactly identified open document. Does not change settings, solve, or claim a valid solver license."""
    return submit('flow_project',dict(document=document))
@mcp.tool()
def sw_flow_results(document:str)->dict:
    """Load last results for the active Flow project in the exact document; read goal values, units, convergence progress and invalid flags. Does not start a solve."""
    return submit('flow_results',dict(document=document))
@mcp.tool()
def sw_flow_export(document:str,output_directory:str)->dict:
    """Export Flow goals JSON/CSV and CURRENT viewport BMP into a NEW absolute directory. Configure a plot first; does not create plots, overwrite files, or solve."""
    return submit('flow_export',dict(document=document,output_directory=output_directory))
@mcp.tool()
def sw_flow_set_material(document:str,project_name:str,feature_uuid:str,expected_path:str,material_path:str,archive_directory:str)->dict:
    """Change an existing Flow material assignment using a verified engineering-database path. Requires expected old path and NEW backup directory. Readback checked, results invalidated. Does not invent material properties or create database entries."""
    return submit('flow_set_material',dict(document=document,project_name=project_name,feature_uuid=feature_uuid,expected_path=expected_path,material_path=material_path,archive_directory=archive_directory))
@mcp.tool()
def sw_flow_snapshot(document:str,project_name:str,output_directory:str)->dict:
    """Export vendor XML plus readable named settings JSON to NEW directory, including fan boundary values, material assignments and mesh settings omitted by legacy feature enumeration. Returns SHA256; not proof of complete physical validity."""
    return submit('flow_snapshot',dict(document=document,project_name=project_name,output_directory=output_directory))
@mcp.tool()
def sw_flow_set_parameter(document:str,project_name:str,feature_uuid:str,parameter_id:int,expected_value:float,value_si:float,expected_unit:int,archive_directory:str)->dict:
    """Edit one verified constant Flow parameter by UUID/ID in SI units after archiving model folder. Requires expected current value/unit and UI/documentation-verified meaning and active mode. Does not support formula/curve parameters. Invalidates previous results; re-solve required."""
    return submit('flow_set_parameter',dict(document=document,project_name=project_name,feature_uuid=feature_uuid,parameter_id=parameter_id,expected_value=expected_value,value_si=value_si,expected_unit=expected_unit,archive_directory=archive_directory))
@mcp.tool()
def sw_flow_parameters(document:str,project_name:str)->dict:
    """Read Flow feature UUIDs, references, parameter IDs, raw SI values, units, formula and dependency types. Alternative inactive parameters may be present; never infer labels from IDs."""
    return submit('flow_parameters',dict(document=document,project_name=project_name))
@mcp.tool()
def sw_flow_preflight(document:str,project_name:str)->dict:
    """Verify exact active Flow project, saved model and active references; read heat-transfer/radiation/mesh flags. Does not validate physical input values."""
    return submit('flow_preflight',dict(document=document,project_name=project_name))
@mcp.tool()
def sw_flow_solve(document:str,project_name:str,result_directory:str,archive_directory:str)->dict:
    """Solve an EXISTING configured Flow project after archiving the entire model directory to a NEW outside directory, including sibling results. The existing result directory must be a direct child of the model directory. Exact project name required. Solve may save the model. Poll; never retry or interact during solve. Success requires fresh FLD and successful solver log; no automatic physics setup or plot creation."""
    return submit('flow_solve',dict(document=document,project_name=project_name,result_directory=result_directory,archive_directory=archive_directory))
@mcp.tool()
def sw_job_status(job_id:str)->dict:
    """Read job stage/result immediately. A long-running COM call is never cancelled or retried automatically."""
    return status(job_id)
@mcp.tool()
def sw_acknowledge_dead_job(job_id:str)->dict:
    """Release a dead-worker lock only after no SW/importer processes remain. Does not retry CAD or terminate a process."""
    return acknowledge(job_id)
@mcp.tool()
def sw_create_part(plan:dict,output_path:str)->dict:
    """Build a NEW part from a millimetre JSON plan (sketches + features), verify its bodies/volume, then save to a new absolute .sldprt path. Plans are data - sketch entities: line/rectangle/corner_rectangle/circle/arc/polygon/slot/spline (a feature needs a CLOSED contour; verified closed ones are rectangle/corner_rectangle/circle/polygon/slot and explicit line loops). Features: extrude_boss (blind or through_all), extrude_cut (blind or through_all), extrude_midplane, fillet, chamfer, shell. Pattern and mirror features are NOT supported on this build and fail loudly - put repeated or mirrored entities in ONE sketch instead. Sketch/feature/element references accept a 1-based index or a literal name. Existing files are never overwritten; a failed plan discards its own unsaved scratch document. Verified is true only when the plan supplies a verify block AND the rebuild reports no errors."""
    return submit('create_part',dict(plan=plan,output_path=output_path))
@mcp.tool()
def sw_create_assembly(plan:dict,output_path:str)->dict:
    """Build a NEW assembly from a millimetre JSON plan (components with x/y/z placement, then mates), then save to a new absolute .sldasm path. Mate types are coincident/concentric/distance/parallel and need exact entity names such as 'Face1@Part1-1'. Never overwrites. Mate error codes are NOT read here: run sw_mate_status on the saved assembly before trusting the fit."""
    return submit('create_assembly',dict(plan=plan,output_path=output_path))
@mcp.tool()
def sw_create_drawing(plan:dict,output_path:str)->dict:
    """Create a NEW drawing from an existing model and save it to a new absolute .slddrw path. Plan keys: part (absolute model path), views (omit for standard views, or list front/top/right/isometric with x/y in mm), notes, exports. Never overwrites."""
    return submit('create_drawing',dict(plan=plan,output_path=output_path))
# Opt-in isolated instances coexist with legacy serial operations through a pool barrier.
from parallel_mcp import register as register_parallel_tools
register_parallel_tools(mcp)
if __name__=='__main__':mcp.run(transport='stdio')
