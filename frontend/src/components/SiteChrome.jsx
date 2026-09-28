import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";
import { useFormat } from "../lib/format";
import { Link, useRouter } from "../lib/router";
import Icon from "./Icon";
import { useOpenPolicy } from "./PolicyDialog";
import { LanguageMenu, ThemeToggle } from "./Preferences";
import { ArrowButton, IconButton, Logo } from "./ui";

function useNavLinks() {
  const { t } = useTranslation();
  return [
    { to: "/#how", label: t("nav.howItWorks") },
    { to: "/library", label: t("nav.library") },
    { to: "/#faq", label: t("nav.questions") },
  ];
}

export function SiteHeader() {
  const { t } = useTranslation();
  const { isGuest } = useAuth();
  const { path } = useRouter();
  const links = useNavLinks();
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => setMenuOpen(false), [path]);

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 8);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  // At the top the header sits flat inside the page frame. Once the page
  // scrolls it becomes a floating bar, inset on every side, so the frame's
  // rounded corners never end up pinned to the window edge and content
  // passing underneath is hidden rather than ghosting through.
  // Margin + padding add up to the same inset either way, so nothing shifts.
  // The header keeps a constant 72px in the page flow and the bar is centred
  // in it, so shrinking to the floating bar never nudges the content below.
  const bar = scrolled
    ? "mx-2 h-[60px] rounded-[20px] bg-sheet/95 px-2 shadow-[0_2px_8px_-4px_rgba(0,0,0,0.08)] ring-1 ring-line backdrop-blur-xl backdrop-saturate-150 md:mx-3 md:px-5"
    : "h-full px-4 md:px-8";

  return (
    <header className="sticky top-0 z-40">
      <div className="flex h-[72px] items-center">
        {/* Three columns with equal outer tracks keep the nav on the page's centre line. */}
        <div className={`grid min-w-0 flex-1 grid-cols-[1fr_auto] items-center gap-4 transition-all duration-300 lg:grid-cols-[1fr_auto_1fr] ${bar}`}>
          <Link to="/" aria-label={t("nav.home")} className="w-max rounded-xl">
            <Logo />
          </Link>

          <nav aria-label={t("nav.main")} className="hidden items-center gap-2 lg:flex">
            {links.map((l) => (
              <Link key={l.to} to={l.to} className="flex h-10 items-center rounded-full bg-stone px-4 text-sm text-ink transition hover:bg-line">
                {l.label}
              </Link>
            ))}
          </nav>

          <div className="flex items-center justify-end gap-1">
            <LanguageMenu className="hidden sm:block" />
            <LanguageMenu compact className="sm:hidden" />
            <ThemeToggle />
            {isGuest && (
              <Link to="/signin" className="hidden h-10 items-center rounded-full px-3 text-sm text-ink-2 transition hover:text-ink md:flex">
                {t("nav.signIn")}
              </Link>
            )}
            <span className="ml-1 hidden md:block">
              <ArrowButton to="/chat" size="sm">
                {t("nav.ask")}
              </ArrowButton>
            </span>
            <IconButton
              icon={menuOpen ? "x" : "menu"}
              label={t("nav.menu")}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((o) => !o)}
              className="lg:hidden"
            />
          </div>
        </div>
      </div>

      {menuOpen && (
        <div
          className={`animate-fade pb-5 pt-3 lg:hidden ${
            scrolled
              ? "mx-2 mt-2 rounded-[20px] bg-sheet/95 px-4 shadow-[0_2px_8px_-4px_rgba(0,0,0,0.08)] ring-1 ring-line backdrop-blur-xl md:mx-3"
              : "border-t border-line bg-sheet px-4"
          }`}
        >
          <nav aria-label={t("nav.main")} className="flex flex-col">
            {links.map((l) => (
              <Link key={l.to} to={l.to} onClick={() => setMenuOpen(false)} className="border-b border-line py-3.5 text-[17px] text-ink">
                {l.label}
              </Link>
            ))}
            {isGuest && (
              <Link to="/signin" className="border-b border-line py-3.5 text-[17px] text-ink">
                {t("nav.signIn")}
              </Link>
            )}
          </nav>
          <ArrowButton to="/chat" className="mt-5 w-full justify-between">
            {t("nav.ask")}
          </ArrowButton>
        </div>
      )}
    </header>
  );
}

// Big footer wordmark that dissolves into grain toward the bottom: the text
// alpha fades on a gradient and each pixel is kept only where it beats a
// noise field, which gives a dithered edge instead of a smooth fade.
function Wordmark() {
  return (
    <svg viewBox="0 0 1000 250" className="block w-full text-ink" role="img" aria-label="Vidhi">
      <defs>
        <linearGradient id="wordmark-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.3" stopColor="#000" stopOpacity="1" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </linearGradient>
        <filter id="wordmark-grain" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="7" result="noise" />
          <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1 0 0 0 0" result="threshold" />
          <feComposite in="SourceAlpha" in2="threshold" operator="arithmetic" k2="1" k3="-1" result="diff" />
          <feComponentTransfer in="diff" result="mask">
            <feFuncA type="linear" slope="14" />
          </feComponentTransfer>
          <feFlood floodColor="currentColor" />
          <feComposite in2="mask" operator="in" />
        </filter>
      </defs>
      <text
        x="500"
        y="210"
        textAnchor="middle"
        textLength="980"
        lengthAdjust="spacingAndGlyphs"
        fontSize="265"
        fontWeight="600"
        fill="url(#wordmark-fade)"
        filter="url(#wordmark-grain)"
        style={{ fontFamily: "Geist, sans-serif" }}
      >
        VIDHI
      </text>
    </svg>
  );
}

export function SiteFooter() {
  const { t } = useTranslation();
  const { year } = useFormat();
  const openPolicy = useOpenPolicy();
  const links = useNavLinks();
  const linkClass = "text-[15px] text-ink-2 transition hover:text-ink";

  return (
    <footer className="mx-auto max-w-[1440px] px-5 pb-8 pt-16 md:px-12">
      <div className="grid gap-12 lg:grid-cols-[1fr_1.4fr]">
        <div className="max-w-md">
          <Logo />
          <p className="mt-4 text-[15px] leading-relaxed text-ink-2">{t("footer.about")}</p>
        </div>
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
          <div>
            <h3 className="mb-4 text-[15px] font-medium">{t("footer.product")}</h3>
            <ul className="space-y-3">
              <li><Link to="/chat" className={linkClass}>{t("nav.ask")}</Link></li>
              {links.map((l) => (
                <li key={l.to}><Link to={l.to} className={linkClass}>{l.label}</Link></li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-4 text-[15px] font-medium">{t("footer.policies")}</h3>
            <ul className="space-y-3">
              {["terms", "privacy", "disclaimer"].map((kind) => (
                <li key={kind}>
                  <button type="button" onClick={() => openPolicy(kind)} className={linkClass}>
                    {t(`policies.${kind}.title`)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-4 text-[15px] font-medium">{t("footer.builtBy")}</h3>
            <ul className="space-y-3 text-[15px] text-ink-2">
              <li>{t("footer.author1")}</li>
              <li>{t("footer.author2")}</li>
            </ul>
          </div>
        </div>
      </div>

      <div className="mt-14 select-none" aria-hidden="false">
        <Wordmark />
      </div>

      <div className="mt-6 flex flex-col gap-3 border-t border-ink/10 pt-6 text-sm text-muted sm:flex-row sm:items-center sm:justify-between">
        <p>{t("footer.copyright", { year: year(new Date().getFullYear()) })}</p>
        <p className="flex items-center gap-2">
          <Icon name="alert" size={15} />
          {t("footer.notAdvice")}
        </p>
      </div>
    </footer>
  );
}
