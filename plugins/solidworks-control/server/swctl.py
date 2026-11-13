"""CLI fallback for existing conversations without refreshed MCP tools."""
import argparse,json,time
from jobs import submit,status,health
p=argparse.ArgumentParser();p.add_argument('action');p.add_argument('--args-file');p.add_argument('--job-id');p.add_argument('--wait',type=float,default=0);a=p.parse_args()
if a.action=='health':r=health()
elif a.action=='status':r=status(a.job_id)
else:
    args=json.loads(open(a.args_file,encoding='utf-8').read()) if a.args_file else {}
    r=submit(a.action,args)
    if a.wait and r.get('status')=='submitted':
        jid=r['job_id'];end=time.time()+min(a.wait,50)
        while time.time()<end:
            r=status(jid)
            if r['status'] not in ('starting','running'):break
            time.sleep(.5)
print(json.dumps(r,ensure_ascii=False,indent=2))
