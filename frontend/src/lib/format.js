import { useMemo } from "react";
import { useTranslation } from "react-i18next";

// Each Indic UI shows numbers in its own script's digits. Change an entry to
// "latn" to use 0-9 for that language instead.
const NUMBERING = {
  hi: "deva",
  mr: "deva",
  bn: "beng",
  pa: "guru",
  gu: "gujr",
  or: "orya",
  ta: "tamldec",
  te: "telu",
  kn: "knda",
  ml: "mlym",
};

// Some browsers ship no locale data for a language (Chrome has none for Odia)
// and would silently fall back to English, digits included. In that case keep
// the language's digits on an en-IN base, so numbers still read natively.
const supported = new Map();
function hasLocaleData(lang) {
  if (!supported.has(lang)) {
    let ok = false;
    try {
      ok = Intl.NumberFormat.supportedLocalesOf([lang]).length > 0;
    } catch {}
    supported.set(lang, ok);
  }
  return supported.get(lang);
}

export function localeTag(lang) {
  const nu = NUMBERING[lang];
  if (!nu) return "en-IN";
  return `${hasLocaleData(lang) ? lang : "en"}-IN-u-nu-${nu}`;
}

export function formatNumber(value, lang, options) {
  return new Intl.NumberFormat(localeTag(lang), options).format(value);
}

export function formatTime(date, lang) {
  // 24-hour in Indic scripts: the 12-hour form still prints a Latin "AM/PM".
  return new Intl.DateTimeFormat(localeTag(lang), {
    hour: "numeric",
    minute: "2-digit",
    hourCycle: lang === "en" ? undefined : "h23",
  }).format(date);
}

export function formatDate(date, lang) {
  return new Intl.DateTimeFormat(localeTag(lang), { dateStyle: "long" }).format(date);
}

export function useFormat() {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || "en";
  return useMemo(
    () => ({
      lang,
      num: (value, options) => formatNumber(value, lang, options),
      year: (value) => formatNumber(value, lang, { useGrouping: false }),
      time: (date) => formatTime(date, lang),
    }),
    [lang]
  );
}
