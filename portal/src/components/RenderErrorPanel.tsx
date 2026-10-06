import { AlertTriangle, Check, Copy } from "lucide-react";
import { useCopy } from "../hooks";
import type { RenderErrorInfo } from "../types";

const COUNT_PAIRS = [
  ["for", "endfor"],
  ["if", "endif"],
] as const;

/** Why a report couldn't be rendered. To whoever manages the report -- the person testing it before
 * anyone else is given access -- it shows the engine's own error, the template text around the failing
 * line, the loop/condition tag counts and a hint; to everyone else, a plain message and a reference
 * that matches the server log. */
export default function RenderErrorPanel({ message, info }: { message: string; info?: RenderErrorInfo }) {
  const [copied, copy] = useCopy();
  const detailed = Boolean(info?.message);
  const everything = info
    ? [
        `${info.type ?? "Error"}: ${info.message ?? message}${info.line ? ` (template line ${info.line})` : ""}`,
        info.hint ?? "",
        info.traceback ?? "",
        `Reference ${info.reference}`,
      ]
        .filter(Boolean)
        .join("\n\n")
    : message;

  return (
    <div className="render-error" role="alert">
      <header className="render-error-head">
        <AlertTriangle size={18} aria-hidden="true" />
        <div>
          <strong>{info?.stage === "template" ? "The template has an error" : "The report couldn't be rendered"}</strong>
          {detailed && <span className="render-error-sub">Only people who manage this report see the details below.</span>}
        </div>
        <button type="button" className="btn btn-sm render-error-copy" onClick={() => copy(everything)}>
          {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
          {copied ? "Copied" : "Copy details"}
        </button>
      </header>

      {detailed ? (
        <p className="render-error-message mono">
          <span className="render-error-type">{info?.type}</span> {info?.message}
          {info?.line ? <span className="render-error-line"> · template line {info.line}</span> : null}
        </p>
      ) : (
        <p className="render-error-plain">{message}</p>
      )}

      {info?.hint && <p className="render-error-hint">{info.hint.replace(/`/g, "").replace(/\*\*/g, "")}</p>}
      {info?.stage === "template" && detailed && (
        <p className="render-error-guide">
          <a href="#/docs/create-a-template/51-loops-and-conditions---p--and-tr-">
            Guide: loops and conditions — when to use {"{% %}"}, {"{%p %}"} and {"{%tr %}"}, with examples you can copy
          </a>
        </p>
      )}

      {info?.shared_tags && info.shared_tags.length > 0 && (
        <div className="render-error-context" aria-label="Paragraphs holding several tags">
          <span className="render-error-label">Paragraph{info.shared_tags.length > 1 ? "s" : ""} holding more than one tag</span>
          <ol>
            {info.shared_tags.map((item) => (
              <li key={`${item.where}-${item.paragraph}`} className="hit">
                <span className="render-error-ln">¶{item.paragraph}</span>
                <code>{item.text}</code>
                <span className="render-error-here">{item.where}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {info?.context && info.context.length > 0 && (
        <div className="render-error-context" aria-label="Template text around the error">
          <span className="render-error-label">Template text around the error</span>
          <ol>
            {info.context.map((line) => (
              <li key={line.line} className={line.hit ? "hit" : undefined}>
                <span className="render-error-ln">{line.line}</span>
                <code>{line.text || " "}</code>
                {line.hit && <span className="render-error-here">← here</span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {info?.tag_counts && (
        <p className="render-error-counts">
          <span className="render-error-label">Tags in this template</span>
          {COUNT_PAIRS.map(([open, close]) => {
            const a = info.tag_counts![open];
            const b = info.tag_counts![close];
            return (
              <span key={open} className={`render-error-count${a !== b ? " off" : ""}`}>
                <code>{open}</code> {a} · <code>{close}</code> {b}
                {a !== b ? " — not equal" : ""}
              </span>
            );
          })}
        </p>
      )}

      {info?.traceback && (
        <details className="render-error-trace">
          <summary>Technical details</summary>
          <pre>{info.traceback}</pre>
        </details>
      )}

      {info && (
        <p className="render-error-ref">
          Reference <code>{info.reference}</code> — the same reference is in the server log with the full traceback.
        </p>
      )}
    </div>
  );
}
