import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { AuditEvent, AuditQuery } from "../types";
import { ActionGlyph, ActorLine, AuditChanges, fmtStamp, stampTitle } from "./AuditParts";
import { LinesSkeleton } from "./Skeletons";

/** A short, self-loading list of the most recent audit events matching
 * `query` -- the compact form used where a full page would be too much:
 * the Dashboard's "Recent changes" and a user's Activity tab. The full,
 * searchable trail is admin/audit/AuditLogPage.tsx. */
export default function AuditFeed({
  query,
  limit = 8,
  emptyText = "Nothing recorded yet.",
}: {
  query: AuditQuery;
  limit?: number;
  emptyText?: string;
}) {
  const [items, setItems] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A stable key for `query`, so an inline object literal doesn't refetch every render.
  const key = JSON.stringify(query);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    api.audit
      .list({ ...query, limit })
      .then((page) => !cancelled && setItems(page.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Couldn't load recent changes"));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` is `query`, serialized
  }, [key, limit]);

  if (error) return <p className="alert alert-error">{error}</p>;
  if (!items) return <LinesSkeleton count={4} />;
  if (items.length === 0) return <p className="muted">{emptyText}</p>;

  return (
    <div className="grid gap-2">
      {items.map((e) => (
        <div key={e.id} className="flex items-start gap-3 rounded-sm border border-border-soft px-3 py-2.5">
          <ActionGlyph action={e.action} size={26} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="text-[0.88rem] font-medium text-text">{e.summary}</span>
              <time className="text-[0.76rem] text-text-faint" dateTime={e.created_at} title={stampTitle(e.created_at)}>
                {fmtStamp(e.created_at)}
              </time>
            </div>
            <ActorLine event={e} />
            <AuditChanges changes={e.changes} max={3} />
          </div>
        </div>
      ))}
    </div>
  );
}
