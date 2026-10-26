import { useState } from "react";

interface Props {
  text: string;
  /** characters shown before "Read more" */
  limit?: number;
}

/** Long article bodies start collapsed. */
export function ReadMore({ text, limit = 280 }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (text.length <= limit) return <div className="article-body">{text}</div>;
  return (
    <div className="article-body">
      {expanded ? text : `${text.slice(0, limit)}…`}{" "}
      <span className="read-more" onClick={() => setExpanded(!expanded)}>
        {expanded ? "Show less" : "Read more"}
      </span>
    </div>
  );
}
