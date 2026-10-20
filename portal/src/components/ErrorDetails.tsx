import { useState } from "react";
import { describeFailure, nextStep, statusLabel, type FailureInfo } from "../errorLog";
import { openRecentErrors } from "./RecentErrorsDialog";

/** Copies text, falling back to a hidden textarea where the Clipboard API isn't available -- a portal served over
 * plain http, as on many LANs. The textarea goes next to the button (`near`): inside an open modal dialog the rest
 * of the page is inert, and text there can't be selected. */
export async function copyText(text: string, near?: HTMLElement | null): Promise<boolean> {
  try {
    if (!navigator.clipboard) throw new Error("no clipboard API");
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "0";
    area.style.opacity = "0";
    (near ?? document.body).appendChild(area);
    area.focus();
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } finally {
      area.remove();
    }
    return ok;
  }
}

export function CopyDetailsButton({ text, label = "Copy details" }: { text: () => string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={async (event) => {
        const near = event.currentTarget.parentElement;
        setState((await copyText(text(), near)) ? "copied" : "failed");
        window.setTimeout(() => setState("idle"), 2000);
      }}
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Couldn't copy" : label}
    </button>
  );
}

/** The technician's half of an error: collapsed under the person-facing message, with everything needed to find it
 * in the server log and a button that copies it for a ticket. */
export default function ErrorDetails({ info, showAll = true }: { info: FailureInfo; showAll?: boolean }) {
  return (
    <details className="error-details">
      <summary>Technical details</summary>
      <dl>
        {info.kind !== "script" && (
          <>
            <dt>Request</dt>
            <dd>
              <code>
                {info.method} {info.path}
              </code>
            </dd>
            <dt>Status</dt>
            <dd>{statusLabel(info.status)}</dd>
          </>
        )}
        <dt>Reference</dt>
        <dd>{info.requestId ? <code>{info.requestId}</code> : "—"}</dd>
        <dt>Time</dt>
        <dd>{new Date(info.when).toLocaleString()}</dd>
        <dt>What next</dt>
        <dd>{nextStep(info)}</dd>
      </dl>
      <div className="error-details-actions">
        <CopyDetailsButton text={() => describeFailure(info)} />
        {showAll && (
          <button type="button" className="btn btn-sm btn-ghost" onClick={openRecentErrors}>
            All recent errors
          </button>
        )}
      </div>
    </details>
  );
}
