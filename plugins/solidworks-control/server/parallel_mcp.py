"""Optional tools; registering them does not start an instance or change a lock."""
def register(mcp):
    import parallel_control as ctl
    @mcp.tool()
    def sw_parallel_health()->dict:
        """Read isolated session leases, per-instance jobs and OS metrics without COM."""
        return ctl.health()
    @mcp.tool()
    def sw_parallel_start(workspace:str)->dict:
        """Start one dedicated SW instance in a NEW/EMPTY exclusive workspace. Explicit PID/creation-time/ROT binding. Max two isolated sessions. Legacy CAD jobs must finish first. Poll sw_job_status, then use returned session_id. Does not touch existing SW documents."""
        return ctl.register(workspace)
    @mcp.tool()
    def sw_parallel_claim(pid:int,created:float,workspace:str)->dict:
        """Claim an existing EMPTY SW instance by exact PID and process creation timestamp from health. Never claims an instance containing documents. Workspace must be NEW/EMPTY and disjoint. Poll the job."""
        return ctl.register(workspace,pid,created)
    @mcp.tool()
    def sw_parallel_execute(session_id:str,action:str,args:dict)->dict:
        """Submit to a ready isolated session. Same instance serializes; separate sessions can overlap. Actions: session, open (native only), inspect, components, mate_status, geometry_inventory, interference, view, activate, save_copy, close_clean, create_part, create_assembly, create_drawing. Same args as legacy action. All model/input/export paths and dependencies must be inside exclusive workspace; title-only identities forbidden. Create-part needs verify. No Flow, settings or neutral import. Poll sw_job_status; no mutation retries after failure/timeout."""
        return ctl.submit(session_id,action,args)
    @mcp.tool()
    def sw_parallel_release(session_id:str)->dict:
        """Release an EMPTY isolated session; close verified clean owned documents first. Never discards/saves documents. Normally exits only an empty process created by this pool, never kills it. Claimed user instances stay running. Legacy barrier released after last session."""
        return ctl.release(session_id)
    @mcp.tool()
    def sw_parallel_reconcile(session_id:str)->dict:
        """Reconcile stale busy metadata only after a durable completed/failed result exists. Never releases uncertain COM work or repeats a CAD operation."""
        return ctl.recover(session_id)
