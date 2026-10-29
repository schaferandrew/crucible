import { useState } from "react";

interface Props {
  tags: string[];
  /** the selected tag, or null for all */
  value: string | null;
  onChange: (tag: string | null) => void;
}

/** "Filter by tag" dropdown in the home page sidebar. */
export function TagFilter({ tags, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tag-filter">
      <div className="tag-filter-trigger" onClick={() => setOpen(!open)}>
        {value ? `# ${value}` : "Filter by tag"} ▾
      </div>
      {open && (
        <div className="tag-filter-menu">
          <div className="tag-filter-option" onClick={() => { onChange(null); setOpen(false); }}>All tags</div>
          {tags.map((tag) => (
            <div
              key={tag}
              className={tag === value ? "tag-filter-option selected" : "tag-filter-option"}
              onClick={() => { onChange(tag); setOpen(false); }}
            >
              {tag}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
