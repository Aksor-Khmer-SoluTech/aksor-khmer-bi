"""Host resource metrics (CPU/RAM/disk/threads) for the admin console's
monitoring page -- read-only, no organization scoping (there's no
tenant-owned data here, just the shared host the api process runs on),
gated behind settings:manage as the closest existing permission for
"operate this deployment" (same sensitivity class as the LDAP config
endpoints in routers/ldap.py, which use the same gate).
"""
from __future__ import annotations

import os
import time

import psutil
from fastapi import APIRouter, Depends

from ..auth import require_permission
from ..models import DiskUsage, SystemMetrics
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/system", tags=["system"])

_process = psutil.Process(os.getpid())


def _disk_usage() -> list[DiskUsage]:
    disks: list[DiskUsage] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            # Unreadable/unmounted between listing and stat-ing it -- skip
            # rather than fail the whole metrics call over one bad mount.
            continue
        disks.append(
            DiskUsage(mountpoint=part.mountpoint, total_bytes=usage.total, used_bytes=usage.used, percent=usage.percent)
        )
    return disks


@router.get("/metrics", summary="Host CPU/RAM/disk/thread metrics", response_model=SystemMetrics)
def get_metrics(_: AuthContext = Depends(require_permission("settings:manage"))) -> SystemMetrics:
    # interval=0.1 blocks briefly to sample a real (non-zero-on-first-call)
    # CPU delta -- fine for an admin-polled endpoint, not a hot path.
    per_core = psutil.cpu_percent(percpu=True, interval=0.1)
    vm = psutil.virtual_memory()

    return SystemMetrics(
        cpu_percent=sum(per_core) / len(per_core) if per_core else 0.0,
        cpu_percent_per_core=per_core,
        cpu_core_count=psutil.cpu_count(logical=False) or 0,
        cpu_thread_count=psutil.cpu_count(logical=True) or 0,
        memory_total_bytes=vm.total,
        memory_used_bytes=vm.used,
        memory_percent=vm.percent,
        disks=_disk_usage(),
        process_thread_count=_process.num_threads(),
        process_count=len(psutil.pids()),
        uptime_seconds=int(time.time() - psutil.boot_time()),
    )
