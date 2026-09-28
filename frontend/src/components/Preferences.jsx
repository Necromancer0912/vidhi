import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePrefs } from "../context/PrefsContext";
import { LANGUAGES, languageInfo } from "../lib/languages";
import Icon from "./Icon";
import { IconButton } from "./ui";

export function LanguageMenu({ compact = false, direction = "down", className = "" }) {
  const { t } = useTranslation();
  const { language, setLanguage } = usePrefs();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("common.language")}
        className="flex h-10 items-center gap-2 rounded-full px-3 text-sm text-ink-2 transition hover:bg-ink/[0.06] hover:text-ink"
      >
        <Icon name="globe" size={17} />
        {!compact && <span>{languageInfo(language).name}</span>}
        <Icon name="chevronDown" size={14} className={`transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          role="menu"
          className={`animate-fade absolute right-0 z-50 w-64 rounded-[18px] border border-line bg-sheet p-1.5 shadow-xl ${
            direction === "up" ? "bottom-12" : "top-12"
          }`}
        >
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              type="button"
              role="menuitemradio"
              aria-checked={lang.code === language}
              lang={lang.code}
              onClick={() => {
                setLanguage(lang.code);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between rounded-[12px] px-3 py-2 text-left text-sm transition hover:bg-stone"
            >
              <span className="text-ink">{lang.name}</span>
              <span className="flex items-center gap-2 text-xs text-muted">
                {language === "en" && lang.english !== lang.name && lang.english}
                {lang.code === language && <Icon name="check" size={15} className="text-leaf" />}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ThemeToggle({ className = "" }) {
  const { t } = useTranslation();
  const { theme, toggleTheme } = usePrefs();
  return (
    <IconButton
      icon={theme === "dark" ? "sun" : "moon"}
      label={theme === "dark" ? t("common.lightMode") : t("common.darkMode")}
      onClick={toggleTheme}
      className={className}
    />
  );
}
