import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../lib/supabaseClient";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const { error: authError } =
      mode === "sign-in"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({
            email,
            password,
            // Without this, Supabase falls back to the project's Auth
            // "Site URL" setting for the confirmation email's redirect --
            // wherever the app actually is (localhost in dev, the deployed
            // URL in prod) still needs to be on that project's allowed
            // redirect URLs list, or Supabase ignores this and falls back
            // anyway.
            options: { emailRedirectTo: window.location.origin },
          });

    setSubmitting(false);

    if (authError) {
      setError(authError.message);
      return;
    }
    navigate("/");
  }

  return (
    <div className="page">
      <h1>Fantasy Copilot</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={6}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {mode === "sign-in" ? "Sign in" : "Sign up"}
        </button>
      </form>
      <button
        type="button"
        className="link-button"
        onClick={() => setMode(mode === "sign-in" ? "sign-up" : "sign-in")}
      >
        {mode === "sign-in"
          ? "Need an account? Sign up"
          : "Already have an account? Sign in"}
      </button>
    </div>
  );
}
