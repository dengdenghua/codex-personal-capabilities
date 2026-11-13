"""Read-only memory admission gate. Never connects to COM or terminates a process."""
from __future__ import annotations
import argparse
import json
from dataclasses import asdict, dataclass

GIB = 1024 ** 3

@dataclass(frozen=True)
class MemoryPolicy:
    warn_private_fraction: float = 0.45
    stop_private_fraction: float = 0.65
    # 2026-10-10: user explicitly requested a looser performance policy.
    # User-authorized relaxed policy: 10% warns; 1 GiB is the hard reserve.
    # Serialized CAD and document ownership stay enforced. This gate limits
    # admission pressure; it does not limit the number of documents opened.
    min_available_fraction: float = 0.0
    min_available_gib: float = 1.0
    warn_available_fraction: float = 0.10

def memory_snapshot():
    import psutil
    vm = psutil.virtual_memory()
    processes = []
    for p in psutil.process_iter(['pid', 'name']):
        if str(p.info['name']).casefold() != 'sldworks.exe':
            continue
        mi = p.memory_info()
        # On Windows private is committed private bytes, not just resident RAM.
        # A small working set can conceal a heavily paged SolidWorks process.
        private = getattr(mi, 'private', None)
        if private is None:
            raise RuntimeError('SolidWorks private committed bytes unavailable')
        processes.append({'pid': p.pid, 'private_bytes': private, 'working_set_bytes': mi.rss, 'thread_count': p.num_threads()})
    return {'physical_total_bytes': vm.total, 'physical_available_bytes': vm.available,
            'solidworks': processes}

def evaluate_memory(snapshot, policy=MemoryPolicy()):
    total = snapshot['physical_total_bytes']
    available = snapshot['physical_available_bytes']
    if total <= 0 or available < 0:
        raise ValueError('Invalid memory sample')
    processes = snapshot['solidworks']
    private = sum(x['private_bytes'] for x in processes)
    reserve = max(policy.min_available_gib * GIB, total * policy.min_available_fraction)
    reasons, warnings = [], []
    # A zero-thread Windows process record cannot run a CAD session. Account for
    # its entire private memory, but do not confuse it with a second live session.
    # The CAD connector independently verifies the live process against ROT and COM PID.
    live_processes = [p for p in processes if p.get('thread_count', 1) != 0]
    if len(live_processes) > 1:
        reasons.append('multiple SolidWorks processes; session identity is ambiguous')
    elif processes and not live_processes:
        reasons.append('SolidWorks process records exist but none has live threads')
    if available < reserve:
        reasons.append('available physical RAM below required reserve')
    elif available < total * policy.warn_available_fraction:
        warnings.append('available RAM below 10%; keep CAD and rendering serial and recycle completed documents')
    if private >= total * policy.stop_private_fraction:
        reasons.append('SolidWorks private committed memory exceeds admission limit')
    elif private >= total * policy.warn_private_fraction:
        warnings.append('recycle completed task documents before another large operation')
    return {'allowed': not reasons, 'status': 'stop' if reasons else ('warning' if warnings else 'ok'),
            'reasons': reasons, 'warnings': warnings, 'sample': snapshot, 'policy': asdict(policy),
            'private_total_gib': round(private/GIB, 2), 'available_gib': round(available/GIB, 2),
            'stop_private_gib': round(total*policy.stop_private_fraction/GIB, 2),
            'required_available_gib': round(reserve/GIB, 2),
            'scope': 'admission only; does not prove UI responsiveness or cancel a running job'}

def inspect_performance():
    try:
        return evaluate_memory(memory_snapshot())
    except Exception as exc:
        return {'allowed': False, 'status': 'unknown', 'reasons': [str(exc)],
                'scope': 'resource state unknown; no new heavy operation admitted'}

def assert_capacity():
    result = inspect_performance()
    if not result['allowed']:
        raise RuntimeError('SolidWorks resource gate: ' + json.dumps(result, ensure_ascii=False))
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='Optional JSON evidence path')
    args = parser.parse_args()
    result = inspect_performance()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        from pathlib import Path
        p = Path(args.output); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, 'utf-8')
    print(text)
    return 0 if result['allowed'] else 4

if __name__ == '__main__':
    raise SystemExit(main())
