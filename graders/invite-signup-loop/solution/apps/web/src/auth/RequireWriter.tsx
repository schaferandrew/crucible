import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

/**
 * Writing requires a signed-in user who has accepted the contributor terms (docs/legal-contributor-terms.md).
 * A profile isn't required.
 */
export function RequireWriter({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <p>Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!user.termsAcceptedAt) return <Navigate to="/welcome" replace />;
  return <>{children}</>;
}
