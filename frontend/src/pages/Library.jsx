import { useDeferredValue, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../components/Icon";
import { SiteFooter, SiteHeader } from "../components/SiteChrome";
import { DOCUMENTS as ALL_DOCUMENTS } from "../lib/documents";
import { useFormat } from "../lib/format";
import { useRouter } from "../lib/router";

const TYPES = {
  "Act / Code": "acts",
  "Rule / Regulation": "rules",
  "Landmark Case": "cases",
  "Guideline / Policy": "guidelines",
  "Other Document": "other",
};
const FILTERS = ["all", "acts", "rules", "cases", "guidelines", "other"];
const PAGE = 40;

const DOCUMENTS = ALL_DOCUMENTS.map((d) => ({ ...d, type: TYPES[d.category] || "other" }));

const COUNTS = DOCUMENTS.reduce(
  (acc, d) => ({ ...acc, [d.type]: (acc[d.type] || 0) + 1 }),
  { all: DOCUMENTS.length }
);

export default function Library() {
  const { t, i18n } = useTranslation(["translation", "documents"]);
  const { num } = useFormat();
  const { navigate } = useRouter();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [limit, setLimit] = useState(PAGE);
  const deferredQuery = useDeferredValue(query);

  // Titles in the current language, sorted in that language's order. Search
  // matches the translated and the English title, so either works.
  const documents = useMemo(() => {
    const collator = new Intl.Collator(i18n.resolvedLanguage);
    return DOCUMENTS.map((d) => {
      const shown = t(d.key, { ns: "documents", defaultValue: d.title });
      return { ...d, shown, search: `${shown} ${d.title}`.toLowerCase() };
    }).sort((a, b) => collator.compare(a.shown, b.shown));
  }, [t, i18n.resolvedLanguage]);

  const results = useMemo(() => {
    const words = deferredQuery.toLowerCase().split(/\s+/).filter(Boolean);
    return documents.filter((d) => (filter === "all" || d.type === filter) && words.every((w) => d.search.includes(w)));
  }, [documents, deferredQuery, filter]);

  const ask = (title) => navigate("/chat", { state: { prompt: t("library.askPrompt", { title }) } });

  return (
    <div className="min-h-screen bg-page">
      <div className="mx-auto max-w-[1440px] px-2 pt-2 md:px-4 md:pt-4">
        <div className="rounded-[26px] bg-sheet md:rounded-[34px]">
          <SiteHeader />
          <main className="flex flex-col gap-2.5 p-2.5 pt-0 md:gap-3 md:p-3 md:pt-0">
            <section className="rounded-[22px] bg-mist px-5 py-14 md:rounded-[var(--radius-panel)] md:px-14 md:py-20">
              <h1 className="display max-w-[16ch] text-[40px] md:text-[60px]">{t("library.title")}</h1>
              <p className="mt-5 max-w-2xl text-[16px] leading-relaxed text-ink-2 md:text-[17px]">{t("library.body")}</p>

              <label className="mt-10 flex h-14 max-w-2xl items-center gap-3 rounded-full bg-sheet px-5 shadow-sm ring-1 ring-line focus-within:ring-ink/40">
                <Icon name="search" size={19} className="text-muted" />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setLimit(PAGE);
                  }}
                  placeholder={t("library.search")}
                  aria-label={t("library.search")}
                  className="w-full bg-transparent text-[16px] text-ink outline-none placeholder:text-muted"
                />
              </label>

              <div className="no-scrollbar -mx-5 mt-5 flex gap-2 overflow-x-auto px-5 md:mx-0 md:flex-wrap md:px-0" role="group" aria-label={t("library.filter")}>
                {FILTERS.map((f) => (
                  <button
                    key={f}
                    type="button"
                    aria-pressed={filter === f}
                    onClick={() => {
                      setFilter(f);
                      setLimit(PAGE);
                    }}
                    className={`flex h-10 shrink-0 items-center gap-2 rounded-full px-4 text-sm transition ${
                      filter === f ? "bg-invert text-on-invert" : "bg-sheet text-ink hover:bg-stone"
                    }`}
                  >
                    {t(`library.types.${f}`)}
                    <span className={filter === f ? "text-on-invert/60" : "text-muted"}>{num(COUNTS[f] || 0)}</span>
                  </button>
                ))}
              </div>
            </section>

            <section className="px-3 pb-10 pt-6 md:px-11" aria-live="polite">
              <p className="mb-2 text-sm text-muted">{t("library.showing", { shown: num(Math.min(limit, results.length)), total: num(results.length) })}</p>
              {results.length === 0 ? (
                <div className="rounded-[18px] bg-stone px-6 py-12 text-center">
                  <p className="font-medium">{t("library.emptyTitle")}</p>
                  <p className="mx-auto mt-2 max-w-md text-[15px] text-ink-2">{t("library.emptyBody")}</p>
                  {query.trim() && (
                    <button
                      type="button"
                      onClick={() => navigate("/chat", { state: { prompt: query.trim() } })}
                      className="mt-5 inline-flex h-10 items-center gap-2 rounded-full bg-invert px-5 text-sm font-medium text-on-invert"
                    >
                      {t("library.askInstead")}
                      <Icon name="arrowRight" size={15} />
                    </button>
                  )}
                </div>
              ) : (
                <ul className="divide-y divide-line">
                  {results.slice(0, limit).map((d) => (
                    <li key={d.key} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex min-w-0 items-start gap-3">
                        <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-stone text-ink-2">
                          <Icon name={d.type === "cases" ? "book" : "file"} size={17} />
                        </span>
                        <div className="min-w-0">
                          <p className="text-[15px] font-medium leading-snug text-ink">{d.shown}</p>
                          <p className="mt-0.5 text-sm text-muted">{t(`library.typeSingular.${d.type}`)}</p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => ask(d.shown)}
                        className="flex min-h-9 shrink-0 items-center gap-1.5 self-start rounded-full border border-line px-4 py-1.5 text-sm text-ink transition hover:border-ink/40 hover:bg-stone sm:self-auto"
                      >
                        {t("library.ask")}
                        <Icon name="arrowRight" size={15} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {results.length > limit && (
                <div className="mt-6 flex justify-center">
                  <button
                    type="button"
                    onClick={() => setLimit((l) => l + PAGE)}
                    className="h-11 rounded-full border border-ink/70 px-6 text-sm font-medium transition hover:bg-stone"
                  >
                    {t("library.more")}
                  </button>
                </div>
              )}
            </section>
          </main>
        </div>
      </div>
      <SiteFooter />
    </div>
  );
}
