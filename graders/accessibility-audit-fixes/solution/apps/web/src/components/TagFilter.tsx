interface Props {
  tags: string[];
  /** the selected tag, or null for all */
  value: string | null;
  onChange: (tag: string | null) => void;
}

/** "Filter by tag" dropdown in the home page sidebar. A native <select>: keyboard, announcements and selection come with it. */
export function TagFilter({ tags, value, onChange }: Props) {
  return (
    <div className="tag-filter">
      <select
        className="tag-filter-trigger"
        aria-label="Filter by tag"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">All tags</option>
        {tags.map((tag) => (
          <option key={tag} value={tag}>{tag}</option>
        ))}
      </select>
    </div>
  );
}
