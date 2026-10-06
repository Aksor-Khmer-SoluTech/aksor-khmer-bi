import { useState } from "react";
import Code from "./Code";
import CopyButton from "./CopyButton";

export interface Snippet {
  label: string;
  language: string;
  code: string;
}

/** A tabbed, syntax-highlighted, copy-buttoned code block — one snippet
 * per integration language (curl / JavaScript / Python), each rendering
 * the real report_id + API base URL + saved sample context so it's
 * actually runnable, not a generic placeholder. */
export default function CodeSnippet({ snippets }: { snippets: Snippet[] }) {
  const [active, setActive] = useState(0);
  const current = snippets[active];

  return (
    <div>
      <div className="snippet-tabs">
        {snippets.map((s, i) => (
          <button
            key={s.label}
            type="button"
            className={`snippet-tab ${i === active ? "active" : ""}`}
            onClick={() => setActive(i)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="snippet-block">
        <CopyButton text={current.code} />
        <Code code={current.code} language={current.language} />
      </div>
    </div>
  );
}
