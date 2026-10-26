import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function RegisterPage() {
  const { setSession } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", email: "", password: "" });
  const [errors, setErrors] = useState<string[]>([]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      setSession(await api.register(form.username, form.email, form.password));
      navigate("/welcome");
    } catch (err) {
      setErrors(err instanceof ApiError ? err.message.split("; ") : [String(err)]);
    }
  }

  return (
    <form className="auth-page" onSubmit={submit}>
      <h1>Sign up</h1>
      {errors.length > 0 && (
        <div role="alert">
          {errors.map((e) => <p key={e}>{e}</p>)}
          {errors.some((e) => e.startsWith("email")) && <Link to="/login">Already have an account? Sign in</Link>}
        </div>
      )}
      <input aria-label="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
      <input aria-label="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      <input aria-label="Password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      <button type="submit">Sign up</button>
    </form>
  );
}
