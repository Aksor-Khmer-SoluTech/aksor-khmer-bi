import { useEffect, useRef } from "react";
import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { json } from "@codemirror/lang-json";
import { bracketMatching, foldGutter, HighlightStyle, indentOnInput, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, placeholder as placeholderExtension } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { theme } from "./SqlEditor";

// Keys stand out from values; strings, numbers and true/false/null each get the colour the SQL editor uses for them.
const highlight = HighlightStyle.define([
  { tag: t.propertyName, color: "var(--accent-strong)", fontWeight: "600" },
  { tag: t.string, color: "var(--success-strong)" },
  { tag: [t.number, t.bool, t.null], color: "var(--highlight-strong)" },
  { tag: [t.punctuation, t.separator, t.brace, t.squareBracket], color: "var(--text-dim)" },
]);

/** A small JSON editor -- the SQL editor's look, with JSON colours: line numbers, folding, matching and
 * auto-closing brackets and quotes, undo, Tab to indent. Whether the text is valid JSON is the caller's to say
 * (StaticSourceFields shows why it isn't). */
export default function JsonEditor({
  value,
  onChange,
  placeholder,
  ariaLabel = "JSON",
  invalid = false,
  rows = 16,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  invalid?: boolean;
  rows?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        foldGutter(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        history(),
        drawSelection(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        json(),
        syntaxHighlighting(highlight),
        EditorState.tabSize.of(2),
        keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, indentWithTab]),
        placeholderExtension(placeholder ?? ""),
        EditorView.contentAttributes.of({ "aria-label": ariaLabel, spellcheck: "false" }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) onChangeRef.current(u.state.doc.toString());
        }),
        theme,
      ],
    });
    view.current = new EditorView({ state, parent: host.current! });
    return () => {
      view.current?.destroy();
      view.current = null;
    };
    // Created once; a change from outside (Insert example, Format) is pushed in below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
  }, [value]);

  const lineHeight = 0.82 * 1.6;
  return (
    <div
      ref={host}
      className={`sql-editor json-editor${invalid ? " invalid" : ""}`}
      style={{ ["--sql-rows" as string]: `${rows * lineHeight + 1}rem` }}
    />
  );
}
