import type { Invite } from "@conduit/shared";
import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** The link in the invite email: pick a username and password, accept the terms, start writing. */
export function InvitePage() {
  const { token = "" } = useParams();
  const { setSession } = useAuth();
  const navigate = useNavigate();
  const [invite, setInvite] = useState<Invite | null>(null);
  const [form, setForm] = useState({ username: "", password: "", accepted: false });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.invite(token).then(setInvite, () => setError("This invite link isn't valid."));
  }, [token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      setSession(await api.acceptInvite(token, form.username, form.password));
      navigate("/editor");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  if (error) return <p role="alert">{error}</p>;
  if (!invite) return <p>Loading…</p>;
  return (
    <form className="invite-page" onSubmit={submit}>
      <h1>{invite.invitedBy} invited you to write for Conduit</h1>
      <p>{invite.email}</p>
      <input aria-label="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
      <input aria-label="Password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      <label>
        <input type="checkbox" checked={form.accepted} onChange={(e) => setForm({ ...form, accepted: e.target.checked })} />
        I accept the contributor terms
      </label>
      <button type="submit" disabled={!form.accepted}>Accept invite</button>
    </form>
  );
}
