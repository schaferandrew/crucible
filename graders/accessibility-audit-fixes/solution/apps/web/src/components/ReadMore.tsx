import { useId, useState } from "react";

interface Props {
  text: string;
  /** characters shown before "Read more" */
  limit?: number;
}

/** Long article bodies start collapsed. */
export function ReadMore({ text, limit = 280 }: Props) {
  const [expanded, setExpanded] = useState(false);
  const textId = useId();
  if (text.length <= limit) return <div className="article-body">{text}</div>;
  return (
    <div className="article-body">
      <span id={textId}>{expanded ? text : `${text.slice(0, limit)}…`}</span>{" "}
      <button type="button" className="read-more" aria-expanded={expanded} aria-controls={textId} onClick={() => setExpanded(!expanded)}>
        {expanded ? "Show less" : "Read more"}
      </button>
    </div>
  );
}
