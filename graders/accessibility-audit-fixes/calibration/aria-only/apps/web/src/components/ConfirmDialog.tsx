interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Confirmation overlay for destructive actions. */
export function ConfirmDialog({ open, title, message, confirmLabel = "Delete", onConfirm, onCancel }: Props) {
  if (!open) return null;
  return (
    <div className="overlay" onClick={onCancel}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="dialog-title">{title}</div>
        <p>{message}</p>
        <div className="dialog-actions">
          <div role="button" className="btn btn-secondary" onClick={onCancel}>Cancel</div>
          <div role="button" className="btn btn-danger" onClick={onConfirm}>{confirmLabel}</div>
        </div>
      </div>
    </div>
  );
}
