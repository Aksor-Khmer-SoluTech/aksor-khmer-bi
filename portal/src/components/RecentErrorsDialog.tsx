import { useEffect, useState } from "react";
import { clearFailures, describeAll, statusLabel, subscribeFailures, type FailureInfo } from "../errorLog";
import { useDialogRef } from "../hooks";
import ErrorDetails, { CopyDetailsButton } from "./ErrorDetails";
import ModalClose from "./ModalClose";

const OPEN_EVENT = "aksor:open-recent-errors";

/** Open the Recent errors list from anywhere. */
export function openRecentErrors() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

/** Everything that failed in this tab since it was opened -- what a person sends their administrator instead of
 * screenshots of the browser's developer tools. Rendered once at the root. */
export default function RecentErrorsDialog() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<FailureInfo[]>([]);
  const ref = useDialogRef(open);

  useEffect(() => subscribeFailures(setEntries), []);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, show);
    return () => window.removeEventListener(OPEN_EVENT, show);
  }, []);

  return (
    <dialog ref={ref} className="modal recent-errors" onCancel={() => setOpen(false)} onClose={() => setOpen(false)}>
      <ModalClose />
      <h2 className="panel-title">Recent errors</h2>
      <p className="muted" style={{ fontSize: "0.85rem" }}>
        What failed in this browser tab since it was opened, newest first. Use <strong>Copy all</strong> and send it to whoever
        runs the server: each entry's reference finds the matching lines in the API log.
      </p>
      {entries.length === 0 ? (
        <p className="muted">Nothing has failed.</p>
      ) : (
        <ol className="recent-errors-list">
          {entries.map((e) => (
            <li key={e.id}>
              <div className="recent-errors-head">
                <span className={`recent-errors-status${e.status >= 500 || e.status === 0 ? " is-server" : ""}`}>
                  {e.kind === "script" ? "Page" : statusLabel(e.status)}
                </span>
                <time dateTime={e.when}>{new Date(e.when).toLocaleTimeString()}</time>
              </div>
              {e.kind !== "script" && (
                <code className="recent-errors-request">
                  {e.method} {e.path}
                </code>
              )}
              <p className="recent-errors-message">{e.message}</p>
              <ErrorDetails info={e} showAll={false} />
            </li>
          ))}
        </ol>
      )}
      <div className="dialog-actions">
        {entries.length > 0 && (
          <>
            <button type="button" className="btn" onClick={clearFailures}>
              Clear
            </button>
            <CopyDetailsButton
              label="Copy all"
              text={() => describeAll(entries, `Aksor Khmer BI portal v${__APP_VERSION__} — ${entries.length} recent error(s)`)}
            />
          </>
        )}
        <button type="button" className="btn btn-primary" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>
    </dialog>
  );
}
