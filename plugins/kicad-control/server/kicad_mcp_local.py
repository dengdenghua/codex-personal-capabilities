"""Local KiCad 10 MCP. Official kicad-python IPC; no upstream API assumptions."""
import os
from pathlib import Path
# KICAD_SYMBOL_DIR is supplied by local discovery or user configuration.
from fastmcp import FastMCP
from kipy import KiCad
from kipy.geometry import Vector2
from kipy.board_types import BoardText
import kicad_sch_api as schapi

mcp=FastMCP('KiCad 10 Local')

def board(): return KiCad().get_board()
def fp_record(f):
 return {'reference':f.reference_field.text.value,'value':f.value_field.text.value,'x_mm':f.position.x/1e6,'y_mm':f.position.y/1e6,'id':f.id.value}
def find_fp(b,reference):
 matches=[f for f in b.get_footprints() if f.reference_field.text.value==reference]
 if len(matches)!=1: raise ValueError(f'Expected one footprint {reference}; found {len(matches)}')
 return matches[0]
def modify(b,item,message):
 c=b.begin_commit()
 try:
  result=b.update_items(item)
  if len(result)!=1: raise RuntimeError('KiCad did not update exactly one item')
  b.push_commit(c,message)
 except Exception:
  b.drop_commit(c); raise
 return result[0]

@mcp.tool()
def connect_kicad()->dict:
 """Check the running KiCad PCB editor IPC connection and version."""
 k=KiCad(); b=k.get_board()
 return {'version':str(k.get_version()),'board':b.name,'project_directory':b.document.project.path}

@mcp.tool()
def get_board_info()->dict:
 """Read actual board counts and all named electrical nets."""
 b=board()
 return {'name':b.name,'footprints':len(b.get_footprints()),'tracks':len(b.get_tracks()),'vias':len(b.get_vias()),'nets':[n.name for n in b.get_nets() if n.name]}

@mcp.tool()
def list_footprints()->list[dict]:
 """Read references, values, UUIDs and positions in millimetres."""
 return [fp_record(f) for f in board().get_footprints()]

@mcp.tool()
def set_footprint_value(reference:str,value:str)->dict:
 """Change a PCB footprint value. Creates an undo entry; call save_board to persist. Does not edit schematic."""
 b=board();f=find_fp(b,reference);f.value_field.text.value=value
 return fp_record(modify(b,f,'MCP: change footprint value'))

@mcp.tool()
def move_footprint(reference:str,x_mm:float,y_mm:float)->dict:
 """Move a footprint in mm with undo. Attached tracks are NOT rerouted; run DRC afterward."""
 b=board();f=find_fp(b,reference);f.position=Vector2.from_xy_mm(x_mm,y_mm)
 return fp_record(modify(b,f,'MCP: move footprint'))

@mcp.tool()
def add_board_text(value:str,x_mm:float,y_mm:float,layer:str='F.Silkscreen')->dict:
 """Add board text on a named layer in mm. Does not save automatically."""
 b=board();t=BoardText();t.value=value;t.position=Vector2.from_xy_mm(x_mm,y_mm);t.layer=b.get_layer_by_name(layer)
 c=b.begin_commit()
 try:
  created=b.create_items(t)
  if len(created)!=1: raise RuntimeError('Text creation failed')
  b.push_commit(c,'MCP: add board text')
 except Exception:
  b.drop_commit(c);raise
 return {'id':created[0].id.value,'value':created[0].value}

@mcp.tool()
def save_board()->dict:
 """Save the current PCB to its existing filename, including pending edits."""
 b=board();b.save();return {'saved':b.name,'directory':b.document.project.path}

@mcp.tool()
def inspect_schematic(path:str)->dict:
 """Read a saved .kicad_sch file. This is file access, not live schematic IPC."""
 s=schapi.load_schematic(path)
 return {'path':str(Path(path).resolve()),'components':[{'reference':c.reference,'value':c.value,'lib_id':c.lib_id} for c in s.components.all()]}

@mcp.tool()
def set_schematic_value(source_path:str,output_path:str,reference:str,value:str)->dict:
 """Edit a schematic component value into a NEW file. Source must be saved and output must not exist. Run ERC after editing."""
 source=Path(source_path).resolve();out=Path(output_path).resolve()
 if out.exists() or out==source: raise ValueError('Choose a new output file to preserve the source schematic')
 if out.suffix!='.kicad_sch': raise ValueError('Output must use .kicad_sch')
 s=schapi.load_schematic(str(source));c=s.components.get(reference)
 if c is None: raise ValueError('Component not found: '+reference)
 c.value=value;s.save(str(out))
 return {'saved':str(out),'reference':reference,'value':value}

if __name__=='__main__': mcp.run(show_banner=False)
