import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { MeterSkeleton, StatRowSkeleton } from "../../components/Skeletons";
import type { SystemMetrics } from "../../types";
import { formatBytes, formatUptime } from "./format";
import { CoreBars, MetricMeter } from "./MetricMeter";

const POLL_MS = 5000;

export default function MonitorPage() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    function poll() {
      api.system
        .metrics()
        .then((m) => {
          if (cancelled) return;
          setMetrics(m);
          setUpdatedAt(new Date());
          setError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof ApiError ? err.message : "Couldn't reach /system/metrics");
        });
    }
    poll();
    timer.current = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Monitor</h1>
          <p className="page-subtitle">Live host resource usage for the machine running the api service.</p>
        </div>
        {updatedAt && <span className="muted mono" style={{ fontSize: "0.78rem" }}>updated {updatedAt.toLocaleTimeString()}</span>}
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {!metrics && !error && (
        <div className="stack" style={{ gap: 20 }}>
          <div className="panel">
            <div className="skel skel-line" style={{ width: 40, height: 15, marginBottom: 8 }} />
            <MeterSkeleton />
          </div>
          <div className="panel">
            <div className="skel skel-line" style={{ width: 70, height: 15, marginBottom: 8 }} />
            <MeterSkeleton />
          </div>
          <div className="panel">
            <div className="skel skel-line" style={{ width: 60, height: 15, marginBottom: 8 }} />
            <MeterSkeleton />
            <MeterSkeleton />
          </div>
          <div className="panel">
            <div className="skel skel-line" style={{ width: 66, height: 15, marginBottom: 8 }} />
            <StatRowSkeleton count={3} />
          </div>
        </div>
      )}

      {metrics && (
        <div className="stack" style={{ gap: 20 }}>
          <div className="panel">
            <div className="spread" style={{ marginBottom: 4 }}>
              <span className="panel-title" style={{ fontSize: "1rem" }}>
                CPU
              </span>
              <span className="muted mono" style={{ fontSize: "0.78rem" }}>
                {metrics.cpu_core_count} cores / {metrics.cpu_thread_count} threads
              </span>
            </div>
            <MetricMeter label="Overall" percent={metrics.cpu_percent} />
            <CoreBars values={metrics.cpu_percent_per_core} />
          </div>

          <div className="panel">
            <span className="panel-title" style={{ fontSize: "1rem" }}>
              Memory
            </span>
            <MetricMeter
              label="RAM"
              percent={metrics.memory_percent}
              sublabel={`${formatBytes(metrics.memory_used_bytes)} / ${formatBytes(metrics.memory_total_bytes)}`}
            />
          </div>

          <div className="panel">
            <span className="panel-title" style={{ fontSize: "1rem" }}>
              Storage
            </span>
            {metrics.disks.length === 0 && <p className="muted">No mounted volumes reported.</p>}
            {metrics.disks.map((d) => (
              <MetricMeter
                key={d.mountpoint}
                label={d.mountpoint}
                percent={d.percent}
                sublabel={`${formatBytes(d.used_bytes)} / ${formatBytes(d.total_bytes)}`}
              />
            ))}
          </div>

          <div className="panel">
            <span className="panel-title" style={{ fontSize: "1rem" }}>
              Process
            </span>
            <div className="stat-row">
              <div>
                <div className="mono stat-number">{metrics.process_thread_count}</div>
                <div className="muted">api threads</div>
              </div>
              <div>
                <div className="mono stat-number">{metrics.process_count}</div>
                <div className="muted">OS processes</div>
              </div>
              <div>
                <div className="mono stat-number">{formatUptime(metrics.uptime_seconds)}</div>
                <div className="muted">host uptime</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
