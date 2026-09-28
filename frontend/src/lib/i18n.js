import i18n from "i18next";
import HttpBackend from "i18next-http-backend";
import { initReactI18next } from "react-i18next";
import { LANGUAGE_CODES, languageInfo } from "./languages";
import { readString, writeString } from "./storage";

const STORAGE_KEY = "vidhi_language";

function initialLanguage() {
  const saved = readString(STORAGE_KEY);
  return LANGUAGE_CODES.includes(saved) ? saved : "en";
}

// Load the Noto family for the active script and put it first in the
// fallback chain, so Latin text keeps Geist and script text gets Noto.
function applyScript(code) {
  const { font } = languageInfo(code);
  const root = document.documentElement;
  root.lang = code;
  root.style.setProperty("--font-script", font ? `"${font}"` : "system-ui");
  if (!font) return;

  const id = `font-${font.replace(/\s+/g, "-").toLowerCase()}`;
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?family=${font.replace(/\s+/g, "+")}:wght@400;500;600&display=swap`;
  document.head.appendChild(link);
}

i18n.on("languageChanged", (code) => {
  writeString(STORAGE_KEY, code);
  applyScript(code);
});

i18n
  .use(HttpBackend)
  .use(initReactI18next)
  .init({
    lng: initialLanguage(),
    fallbackLng: "en",
    supportedLngs: LANGUAGE_CODES,
    load: "languageOnly",
    interpolation: { escapeValue: false },
    ns: ["translation"],
    defaultNS: "translation",
    backend: { loadPath: "/locales/{{lng}}/{{ns}}.json" },
    returnNull: false,
  });

applyScript(i18n.language || initialLanguage());

export default i18n;
