"""Read-only MCP acceptance on a restored optical library; reports stay outside Git."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import optics_private

def verify(config,output):
    record=optics_private.read(config)['servers']['optics_workbench'];q=queue.Queue()
    child=subprocess.Popen([record['command'],*record['args']],cwd=record['cwd'],env={**os.environ,**record['env']},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8')
    def reader():
        for line in child.stdout:q.put(line)
        q.put(None)
    threading.Thread(target=reader,daemon=True).start();serial=0
    def rpc(method,params):
        nonlocal serial
        serial+=1;child.stdin.write(json.dumps({'jsonrpc':'2.0','id':serial,'method':method,'params':params})+'\n');child.stdin.flush()
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            line=q.get(timeout=max(.01,deadline-time.monotonic()))
            if line is None:raise RuntimeError('MCP exited before response')
            response=json.loads(line)
            if response.get('id')==serial:
                if 'error' in response:raise RuntimeError('MCP protocol failed')
                return response['result']
        raise TimeoutError('MCP request timed out')
    def tool(name,args=None):
        reply=rpc('tools/call',{'name':name,'arguments':args or {}})
        if reply.get('isError'):raise RuntimeError(name+' failed: '+reply['content'][0]['text'])
        return json.loads(reply['content'][0]['text'])['data']
    try:
        rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'optics-recovery-acceptance','version':'1'}})
        child.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');child.stdin.flush()
        tools=rpc('tools/list',{})['tools'];stats=tool('optics_stats');graph=tool('optics_graph_stats');private=tool('optics_private_status')
        assert private['lens_configured'] and private['workflow_memory_configured'] and private['path_map_configured']
        knowledge=tool('optics_search_knowledge',{'query':'复眼','limit':1});assert knowledge
        reference=tool('optics_get_reference',{'slug':knowledge[0]['slug']});assert reference['body']
        nodes=tool('optics_search_graph',{'query':'复眼','limit':1})['items'];assert nodes
        neighbors=tool('optics_graph_neighbors',{'node_id':nodes[0]['id']});assert neighbors['nodes']
        memories=tool('optics_search_memory',{'query':'','limit':1});assert memories
        workflow=tool('optics_search_workflow_memory',{'query':'','limit':1});assert workflow['entries']
        lens=tool('optics_search_lens',{'kind':'cases','query':'','limit':1});assert lens['rows']
        case=tool('optics_lens_detail',{'kind':'cases','identifier':str(lens['rows'][0]['id'])});assert case['surfaces']
        source=tool('optics_resolve_source',{'identity':case['source']['sha256']});assert source['verified']
        projects=tool('optics_list_prototypes');assert len(projects)==stats['projects']
        report={'status':'passed' if private.get('restoration_complete',True) else 'passed_for_available_data','missing_original_identities':private.get('missing_original_identities',0),'tools':len(tools),'documents':stats['documents'],'projects':stats['projects'],'graph_nodes':graph['nodes'],'graph_memories':graph['memories'],'lens_sources':private['lens_sources'],'lens_cases':private['lens_cases'],'workflow_entries':private['workflow_entries'],'checks':['Chinese knowledge retrieval','full reference readback','graph and neighbors','graph memory','offline workflow memory','lens prescription detail','restored source SHA256','project inventory'],'native_simulation':'not_performed','source_mutations':'none'}
        optics_private.write(optics_private.outside(output),report);print(json.dumps(report,ensure_ascii=False))
        return report
    finally:
        child.stdin.close()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        child.stdout.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--report',required=True);a=p.parse_args();verify(a.config,a.report)
