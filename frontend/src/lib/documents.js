import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import statutes from "../data/statutes.json";

// Must match document_key() in scripts/translate_locales.py.
export const docKey = (filename) => filename.replace(/(\.pdf)?\.txt$/i, "").replace(/[^A-Za-z0-9]+/g, "_");

const normalise = (title) => String(title || "").toLowerCase().replace(/[^a-z0-9]/g, "");

export const DOCUMENTS = statutes.map((d) => ({ key: docKey(d.filename), title: d.title, category: d.category }));

// Citations arrive from the server with slightly different punctuation
// ("Payment of Wages Act 1936"), so match on letters and digits only.
const KEY_BY_TITLE = new Map(DOCUMENTS.map((d) => [normalise(d.title), d.key]));

// Returns (englishTitle) => title in the current language, falling back to
// the English title for documents outside the library or not yet translated.
// No suspense: the page renders in English and updates once the file loads.
export function useDocumentTitle() {
  const { t } = useTranslation("documents", { useSuspense: false });
  return useCallback(
    (title) => {
      const key = KEY_BY_TITLE.get(normalise(title));
      return key ? t(key, { defaultValue: title }) : title;
    },
    [t]
  );
}
