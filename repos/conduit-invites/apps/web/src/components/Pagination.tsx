interface Props {
  total: number;
  pageSize: number;
  page: number; // 0-based
  onChange: (page: number) => void;
}

/** Numbered page links for offset-based lists. */
export function Pagination({ total, pageSize, page, onChange }: Props) {
  const pages = Math.ceil(total / pageSize);
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pagination">
      <ul className="pagination">
        {Array.from({ length: pages }, (_, i) => (
          <li key={i}>
            <button type="button" aria-current={i === page ? "page" : undefined} onClick={() => onChange(i)}>
              {i + 1}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
