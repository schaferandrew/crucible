import { type FormEvent, useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** First-run onboarding: set up a profile and accept the contributor terms. */
export function WelcomePage() {
  const { user, ready, setSession } = useAuth();
  const navigate = useNavigate();
  const [bio, setBio] = useState("");
  const [accepted, setAccepted] = useState(false);

  // Invited accounts don't use this screen; send them to the editor.
  useEffect(() => {
    if (user?.accountState === "invited") navigate("/editor", { replace: true });
  }, [user, navigate]);

  if (!ready) return <p>Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.onboardingComplete) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!accepted) return;
    setSession(await api.completeOnboarding(bio));
    navigate("/editor");
  }

  return (
    <form className="welcome-page" onSubmit={submit}>
      <h1>Welcome to Conduit</h1>
      <label>
        A short bio
        <textarea value={bio} onChange={(e) => setBio(e.target.value)} />
      </label>
      <label>
        <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
        I accept the contributor terms
      </label>
      <button type="submit" disabled={!accepted}>Start writing</button>
    </form>
  );
}
