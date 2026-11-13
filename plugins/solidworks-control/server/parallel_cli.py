"""CLI available immediately without restarting an active MCP server."""
import argparse,json,time
import parallel_control as ctl
import jobs

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['health','start','claim','run','release','recover','status'])
    p.add_argument('--workspace');p.add_argument('--pid',type=int);p.add_argument('--created',type=float)
    p.add_argument('--session');p.add_argument('--action');p.add_argument('--args-file');p.add_argument('--job-id')
    p.add_argument('--wait',type=float,default=0);a=p.parse_args()
    if a.command=='health':result=ctl.health()
    elif a.command=='start':result=ctl.register(a.workspace)
    elif a.command=='claim':result=ctl.register(a.workspace,a.pid,a.created)
    elif a.command=='release':result=ctl.release(a.session)
    elif a.command=='recover':result=ctl.recover(a.session)
    elif a.command=='status':result=jobs.status(a.job_id)
    else:result=ctl.submit(a.session,a.action,json.load(open(a.args_file,encoding='utf-8')) if a.args_file else {})
    if a.wait and result.get('status')=='submitted':
        original=result;deadline=time.monotonic()+min(a.wait,50)
        while time.monotonic()<deadline:
            result=jobs.status(original['job_id'])
            if result['status'] not in ('starting','running'):break
            time.sleep(.5)
        result['session_id']=original['session_id']
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
