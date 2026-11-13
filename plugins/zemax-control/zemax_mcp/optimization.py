"""Bounded native optimization; no application startup or process termination."""
import math


def run_optimization(z, method, cores, cycles, timeout_seconds):
    if method not in ('local', 'hammer', 'global'):
        raise ValueError('method must be local, hammer or global')
    names = {0: 'Automatic', 1: 'Fixed_1_Cycle', 5: 'Fixed_5_Cycles',
             10: 'Fixed_10_Cycles', 50: 'Fixed_50_Cycles'}
    if type(cycles) is not int or cycles not in names:
        raise ValueError('cycles must be 0, 1, 5, 10 or 50 (native supported counts)')
    if method != 'local' and cycles != 0:
        raise ValueError('cycles applies only to local optimization')
    if type(cores) is not int or not 1 <= cores <= 256:
        raise ValueError('cores must be 1 to 256')
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
        raise ValueError('timeout_seconds must be finite, > 0 and <= 300')
    api = z.zosapi.Tools.Optimization
    cycle = getattr(api.OptimizationCycles, names[cycles]) if method == 'local' else None
    before = float(z.system.MFE.CalculateMeritFunction())
    opener = {'local': 'OpenLocalOptimization', 'hammer': 'OpenHammerOptimization',
              'global': 'OpenGlobalOptimization'}[method]
    opt = getattr(z.system.Tools, opener)()
    if opt is None:
        raise RuntimeError('Native optimization tool could not be opened')
    z._pending_optimization = opt
    try:
        if method == 'local':
            opt.Algorithm = api.OptimizationAlgorithm.DampedLeastSquares
            opt.Cycles = cycle
        opt.NumberOfCores = cores
        native_status = str(opt.RunAndWaitWithTimeout(float(timeout_seconds)))
        timed_out = native_status == 'TimedOut' or bool(opt.IsRunning)
        if opt.IsRunning:
            opt.Cancel()
            opt.WaitWithTimeout(5.0)
        if opt.IsRunning:
            raise RuntimeError('Optimization still running after cancellation; session blocked until it stops. Do not retry.')
        if native_status in ('FailedToStart', 'InvalidTimeout') or (not timed_out and not opt.Succeeded):
            raise RuntimeError('Native optimization failed: ' + str(opt.ErrorMessage))
        after = float(z.system.MFE.CalculateMeritFunction())
        return dict(method=method, merit_before=before, merit_after=after,
                    improved=after < before, requested_cycles=cycles,
                    cycle_mode=names[cycles] if method == 'local' else None,
                    timeout_seconds=timeout_seconds, timed_out=timed_out,
                    completed=not timed_out, native_status=native_status,
                    interpretation='Merit change is not independent optical acceptance; partial changes remain after cancellation.')
    finally:
        if opt.IsRunning:
            opt.Cancel()
        else:
            opt.Close()
            z._pending_optimization = None
