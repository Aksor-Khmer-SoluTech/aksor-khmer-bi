import { meterState } from "./format";

export function MetricMeter({
  label,
  percent,
  sublabel,
}: {
  label: string;
  percent: number;
  sublabel?: string;
}) {
  const state = meterState(percent);
  return (
    <div className="meter-row">
      <div className="meter-row-head">
        <span className="meter-label">{label}</span>
        <span className="mono meter-value">
          {percent.toFixed(1)}%{sublabel ? ` · ${sublabel}` : ""}
          <span className={`meter-state meter-state-${state}`}>{state}</span>
        </span>
      </div>
      <div className="meter">
        <div className={`meter-fill meter-fill-${state}`} style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
    </div>
  );
}

/** Compact per-core view — a row of thin vertical bars, one per logical
 * CPU, height proportional to that core's utilization. */
export function CoreBars({ values }: { values: number[] }) {
  return (
    <div className="core-bars" role="img" aria-label={`${values.length} CPU cores`}>
      {values.map((v, i) => (
        <div key={i} className="core-bar-track" title={`core ${i}: ${v.toFixed(0)}%`}>
          <div className={`core-bar-fill core-bar-fill-${meterState(v)}`} style={{ height: `${Math.max(4, v)}%` }} />
        </div>
      ))}
    </div>
  );
}
