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
      <div role="button" aria-haspopup="listbox" aria-expanded={open} aria-label="Filter by tag" className="tag-filter-trigger" onClick={() => setOpen(!open)}>
        {value ? `# ${value}` : "Filter by tag"} ▾
      </div>
      {open && (
        <div role="listbox" className="tag-filter-menu">
          <div role="option" aria-selected={value === null} className="tag-filter-option" onClick={() => { onChange(null); setOpen(false); }}>All tags</div>
          {tags.map((tag) => (
            <div
              key={tag}
              role="option"
              aria-selected={tag === value}
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
