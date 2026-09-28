import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { readString, writeString } from "../lib/storage";

const PrefsContext = createContext(null);

export function PrefsProvider({ children }) {
  const { i18n } = useTranslation();
  // theme-init.js has already applied the class; read it back rather than recompute.
  const [theme, setThemeState] = useState(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light"
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  // Follow the OS setting until the user picks a theme explicitly.
  useEffect(() => {
    if (readString("vidhi_theme")) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e) => setThemeState(e.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const setTheme = useCallback((next) => {
    writeString("vidhi_theme", next);
    setThemeState(next);
  }, []);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      toggleTheme: () => setTheme(theme === "dark" ? "light" : "dark"),
      language: i18n.resolvedLanguage || i18n.language || "en",
      setLanguage: (code) => i18n.changeLanguage(code),
    }),
    [theme, setTheme, i18n, i18n.language, i18n.resolvedLanguage]
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs() {
  return useContext(PrefsContext);
}
