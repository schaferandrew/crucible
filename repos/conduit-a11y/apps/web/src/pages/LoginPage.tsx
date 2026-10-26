import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await login(email, password);
      navigate("/");
    } catch {
      setError("email or password is invalid");
    }
  }

  return (
    <form className="auth-page" onSubmit={submit}>
      <h1>Sign in</h1>
      {error && <p role="alert">{error}</p>}
      <input aria-label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input aria-label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="submit">Sign in</button>
    </form>
  );
}
