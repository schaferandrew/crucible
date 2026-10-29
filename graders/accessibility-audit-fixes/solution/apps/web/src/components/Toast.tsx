import { useEffect, useState } from "react";

/**
 * Brief confirmation ("Article published") that fades after a few seconds. The live region is always
 * in the page, so screen readers announce the message when it is added to it.
 */
export function Toast({ message }: { message: string | null }) {
  const [visible, setVisible] = useState(Boolean(message));
  useEffect(() => {
    setVisible(Boolean(message));
    if (!message) return;
    const timer = setTimeout(() => setVisible(false), 4000);
    return () => clearTimeout(timer);
  }, [message]);
  return (
    <div role="status">
      {visible && message ? <div className="toast">{message}</div> : null}
    </div>
  );
}
