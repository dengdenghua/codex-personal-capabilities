"""Machine paths and private state are configured locally, never in the repository."""
import os
from pathlib import Path

def data_root():
    return Path(os.environ.get('PERSONAL_MCP_DATA', Path.home()/'.codex/personal-mcp-data'))/'solidworks'

def required(name):
    value=os.environ.get(name)
    if not value:raise RuntimeError('Missing local configuration: '+name+'; run the runtime doctor.')
    return Path(value)

def executable():return required('SOLIDWORKS_EXE')
def constants():return required('SOLIDWORKS_TLB')
def templates():return required('SOLIDWORKS_TEMPLATES')
def flow_home():return required('SOLIDWORKS_FLOW_HOME')
