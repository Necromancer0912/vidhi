import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon, { GoogleMark } from "../components/Icon";
import { useOpenPolicy } from "../components/PolicyDialog";
import { LanguageMenu, ThemeToggle } from "../components/Preferences";
import { Logo } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { ApiError, describeError } from "../lib/api";
import { Link, useRouter } from "../lib/router";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

const SERVER_MESSAGES = [
  [/invalid email or password/i, "signin.wrongPassword"],
  [/already exists/i, "signin.emailTaken"],
  [/valid email/i, "signin.invalidEmail"],
  [/15 minutes/i, "signin.lockedOut"],
  [/google/i, "signin.googleFailed"],
];

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

const inputClass =
  "h-12 w-full rounded-[14px] border border-line bg-sheet px-4 text-[15px] text-ink outline-none transition placeholder:text-muted focus:border-ink/60";

export default function SignIn() {
  const { t } = useTranslation();
  const { navigate } = useRouter();
  const openPolicy = useOpenPolicy();
  const { isGuest, sessionExpired, dismissSessionExpired, signIn, signUp, signInWithGoogle } = useAuth();

  const [mode, setMode] = useState("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const googleClient = useRef(null);

  const creating = mode === "signup";

  useEffect(() => {
    if (!isGuest) navigate("/chat", { replace: true });
  }, [isGuest, navigate]);

  const fail = (err) => {
    // The server answers in English; show known cases in the reader's language.
    const known = SERVER_MESSAGES.find(([pattern]) => pattern.test(err.message || ""));
    if (known) setError(t(known[1]));
    else setError(err instanceof ApiError ? describeError(err, t) : t("errors.generic"));
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (creating && password.length < 8) {
      setError(t("signin.passwordTooShort"));
      return;
    }
    setPending(true);
    try {
      if (creating) await signUp(name.trim(), email.trim(), password);
      else await signIn(email.trim(), password);
      dismissSessionExpired();
    } catch (err) {
      fail(err);
    } finally {
      setPending(false);
    }
  };

  const onGoogle = () => {
    setError("");
    if (!window.google?.accounts?.oauth2) {
      setError(t("signin.googleUnavailable"));
      return;
    }
    if (!googleClient.current) {
      googleClient.current = window.google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: "openid email profile",
        callback: async (response) => {
          if (!response?.access_token) {
            if (response?.error && response.error !== "access_denied") setError(t("signin.googleFailed"));
            return;
          }
          setPending(true);
          try {
            await signInWithGoogle(response.access_token);
            dismissSessionExpired();
          } catch (err) {
            fail(err);
          } finally {
            setPending(false);
          }
        },
        error_callback: (err) => {
          if (err?.type !== "popup_closed") setError(t("signin.googleFailed"));
        },
      });
    }
    googleClient.current.requestAccessToken();
  };

  return (
    <div className="min-h-screen bg-page p-2 md:p-4">
      <div className="mx-auto grid min-h-[calc(100vh-16px)] max-w-[1440px] gap-2.5 rounded-[26px] bg-sheet p-2.5 md:min-h-[calc(100vh-32px)] md:gap-3 md:rounded-[34px] md:p-3 lg:grid-cols-[1fr_1.05fr]">
        <aside className="hidden flex-col justify-between rounded-[var(--radius-panel)] bg-lime p-12 text-on-lime lg:flex">
          <Link to="/" className="w-max rounded-xl" aria-label={t("nav.home")}>
            <Logo onLime />
          </Link>
          <div>
            <h1 className="display max-w-[14ch] text-[52px]">{t("signin.asideTitle")}</h1>
            <ul className="mt-10 space-y-5">
              {["b1", "b2", "b3"].map((k) => (
                <li key={k} className="flex gap-3 text-[16px] leading-relaxed">
                  <span className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#11130f] text-lime">
                    <Icon name="check" size={14} strokeWidth={2.4} />
                  </span>
                  {t(`signin.${k}`)}
                </li>
              ))}
            </ul>
          </div>
          <p className="max-w-md text-sm text-[#3a3f35]">{t("signin.asideNote")}</p>
        </aside>

        <main className="flex flex-col rounded-[var(--radius-panel)] px-4 py-5 md:px-10">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center gap-2 rounded-full py-2 pr-3 text-sm text-ink-2 transition hover:text-ink">
              <Icon name="arrowLeft" size={17} />
              {t("signin.back")}
            </Link>
            <div className="flex items-center">
              <LanguageMenu compact />
              <ThemeToggle />
            </div>
          </div>

          <div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center py-10">
            <Link to="/" className="mb-8 w-max lg:hidden" aria-label={t("nav.home")}>
              <Logo />
            </Link>
            <h2 className="display text-[34px] md:text-[40px]">{creating ? t("signin.createTitle") : t("signin.title")}</h2>
            <p className="mt-2 text-[15px] text-ink-2">{creating ? t("signin.createSubtitle") : t("signin.subtitle")}</p>

            {sessionExpired && (
              <p className="mt-6 flex items-center gap-2 rounded-[14px] bg-stone px-4 py-3 text-sm text-ink-2">
                <Icon name="clock" size={16} />
                {t("errors.sessionExpired")}
              </p>
            )}

            <div role="tablist" className="mt-8 grid grid-cols-2 rounded-full bg-stone p-1">
              {["signin", "signup"].map((m) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={mode === m}
                  onClick={() => {
                    setMode(m);
                    setError("");
                  }}
                  className={`min-h-10 rounded-full px-2 py-1.5 text-sm font-medium leading-snug transition ${mode === m ? "bg-sheet text-ink shadow-sm" : "text-muted hover:text-ink"}`}
                >
                  {m === "signin" ? t("signin.tabSignIn") : t("signin.tabCreate")}
                </button>
              ))}
            </div>

            {GOOGLE_CLIENT_ID && (
              <>
                <button
                  type="button"
                  onClick={onGoogle}
                  disabled={pending}
                  className="mt-6 flex min-h-12 w-full items-center justify-center gap-3 rounded-full border border-line px-4 py-2 text-[15px] font-medium transition hover:bg-stone disabled:opacity-60"
                >
                  <GoogleMark />
                  {t("signin.google")}
                </button>
                <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-wider text-muted">
                  <span className="h-px flex-1 bg-line" />
                  {t("signin.or")}
                  <span className="h-px flex-1 bg-line" />
                </div>
              </>
            )}

            <form onSubmit={onSubmit} className={`space-y-4 ${GOOGLE_CLIENT_ID ? "" : "mt-6"}`}>
              {creating && (
                <Field label={t("signin.name")}>
                  <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required maxLength={80} />
                </Field>
              )}
              <Field label={t("signin.email")}>
                <input
                  className={inputClass}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  inputMode="email"
                  required
                  maxLength={254}
                />
              </Field>
              <Field label={t("signin.password")} hint={creating ? t("signin.passwordHint") : null}>
                <div className="relative">
                  <input
                    className={`${inputClass} pr-12`}
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete={creating ? "new-password" : "current-password"}
                    required
                    minLength={creating ? 8 : 1}
                    maxLength={128}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? t("signin.hidePassword") : t("signin.showPassword")}
                    className="absolute right-1.5 top-1.5 grid h-9 w-9 place-items-center rounded-full text-muted transition hover:text-ink"
                  >
                    <Icon name={showPassword ? "eyeOff" : "eye"} size={18} />
                  </button>
                </div>
              </Field>

              {error && (
                <p role="alert" className="flex items-start gap-2 rounded-[14px] bg-danger/10 px-4 py-3 text-sm text-danger">
                  <Icon name="alert" size={16} className="mt-0.5" />
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={pending}
                className="mt-2 flex min-h-12 w-full items-center justify-center rounded-full bg-invert px-4 py-2 text-[15px] font-medium text-on-invert transition hover:opacity-90 disabled:opacity-60"
              >
                {pending ? t("signin.working") : creating ? t("signin.submitCreate") : t("signin.submitSignIn")}
              </button>
            </form>

            <p className="mt-5 text-center text-xs leading-relaxed text-muted">
              {t("signin.agreePrefix")}{" "}
              <button type="button" onClick={() => openPolicy("terms")} className="underline underline-offset-2 hover:text-ink">
                {t("policies.terms.title")}
              </button>{" "}
              {t("signin.agreeAnd")}{" "}
              <button type="button" onClick={() => openPolicy("privacy")} className="underline underline-offset-2 hover:text-ink">
                {t("policies.privacy.title")}
              </button>
              .
            </p>

            <div className="mt-8 rounded-[18px] bg-stone p-4 text-center">
              <Link to="/chat" className="text-[15px] font-medium text-ink underline decoration-lime-strong decoration-2 underline-offset-4">
                {t("signin.guest")}
              </Link>
              <p className="mt-1 text-xs text-muted">{t("signin.guestNote")}</p>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
