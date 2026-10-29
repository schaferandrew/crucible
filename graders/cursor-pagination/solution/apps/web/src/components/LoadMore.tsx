interface Props {
  /** the response's nextCursor; the button is gone on the last page */
  cursor: string | null;
  loading: boolean;
  onClick: () => void;
}

/** "Load more" for cursor-paged lists. */
export function LoadMore({ cursor, loading, onClick }: Props) {
  if (!cursor) return null;
  return (
    <button type="button" className="load-more" disabled={loading} onClick={onClick}>
      Load more
    </button>
  );
}
