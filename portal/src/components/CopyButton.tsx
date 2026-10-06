import { useCopy } from "../hooks";

export default function CopyButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, copy] = useCopy();
  return (
    <button
      type="button"
      className={`copy-btn ${copied ? "copied" : ""} ${className}`}
      onClick={() => copy(text)}
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}
