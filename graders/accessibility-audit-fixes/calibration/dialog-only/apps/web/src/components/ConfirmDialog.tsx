import { useEffect, useId, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmation overlay for destructive actions. A native modal <dialog>: the browser makes the page
 * behind it inert, keeps Tab inside, closes on Escape and gives focus back to what opened it.
 */
export function ConfirmDialog({ open, title, message, confirmLabel = "Delete", onConfirm, onCancel }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="overlay"
      aria-labelledby={titleId}
      // Escape: let the parent decide, so open stays the single source of truth
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      // a click on the backdrop lands on the <dialog> itself
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      {open && (
        <div className="dialog">
          <div className="dialog-title" id={titleId}>{title}</div>
          <p>{message}</p>
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
            <button type="button" className="btn btn-danger" onClick={onConfirm}>{confirmLabel}</button>
          </div>
        </div>
      )}
    </dialog>
  );
}
