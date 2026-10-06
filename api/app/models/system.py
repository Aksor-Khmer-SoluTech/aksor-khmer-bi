from pydantic import BaseModel, Field


class DiskUsage(BaseModel):
    mountpoint: str
    total_bytes: int
    used_bytes: int
    percent: float


class SystemMetrics(BaseModel):
    cpu_percent: float = Field(..., description="Overall CPU utilization, averaged across cores")
    cpu_percent_per_core: list[float]
    cpu_core_count: int = Field(..., description="Physical cores")
    cpu_thread_count: int = Field(..., description="Logical CPUs (threads)")
    memory_total_bytes: int
    memory_used_bytes: int
    memory_percent: float
    disks: list[DiskUsage]
    process_thread_count: int = Field(..., description="Threads held by this api process")
    process_count: int = Field(..., description="Total OS process count")
    uptime_seconds: int = Field(..., description="Host uptime, seconds since boot")
