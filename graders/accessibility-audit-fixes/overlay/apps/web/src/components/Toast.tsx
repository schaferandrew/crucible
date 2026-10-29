import { useEffect, useState } from "react";

/** Brief confirmation ("Article published") that fades after a few seconds. */
export function Toast({ message }: { message: string | null }) {
  const [visible, setVisible] = useState(Boolean(message));
  useEffect(() => {
    setVisible(Boolean(message));
    if (!message) return;
    const timer = setTimeout(() => setVisible(false), 4000);
    return () => clearTimeout(timer);
  }, [message]);
  if (!visible || !message) return null;
  return <div className="toast">{message}</div>;
}
