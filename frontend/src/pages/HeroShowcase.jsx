import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../components/Icon";
import { usePrefs } from "../context/PrefsContext";
import { useFormat } from "../lib/format";
import { LANGUAGES } from "../lib/languages";

const INTERVAL_MS = 6000;

// Composition of the indexed library (frontend/src/data/statutes.json).
const LIBRARY_MIX = [
  { key: "acts", count: 251 },
  { key: "rules", count: 171 },
  { key: "other", count: 30 },
  { key: "cases", count: 22 },
  { key: "guidelines", count: 20 },
];

// Claims from a real answer about the Payment of Wages Act, 1936; 0.88 is the
// source-match score that answer received in testing.
const EXAMPLE_CLAIMS = [
  { key: "c1", section: 5 },
  { key: "c2", section: 7 },
  { key: "c3", section: 15 },
];

const card = "w-full rounded-[20px] bg-sheet p-5 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.35)]";
const caption = "flex w-full items-center gap-3 rounded-[16px] bg-sheet/95 p-3.5 shadow-lg backdrop-blur";
const chip = "grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-lime text-on-lime";

function CardHeader({ value, badge, title, aside }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-[34px] font-medium leading-none tracking-[-0.03em] text-ink">
          {value}
          <span className="rounded-md bg-leaf px-1.5 py-0.5 text-[11px] font-medium tracking-normal text-white dark:text-[#11130f]">{badge}</span>
        </p>
        <p className="mt-2 text-sm text-muted">{title}</p>
      </div>
      {aside}
    </div>
  );
}

function LibrarySlide() {
  const { t } = useTranslation();
  const { num } = useFormat();
  const max = LIBRARY_MIX[0].count;
  return (
    <>
      <div className={card}>
        <CardHeader
          value={num(494)}
          badge={t("landing.hero.cardBadge")}
          title={t("landing.hero.cardTitle")}
          aside={
            <p className="text-right text-xs leading-snug text-muted">
              <span className="block text-base font-medium text-ink">{num(72771)}</span>
              {t("landing.hero.cardPassages")}
            </p>
          }
        />
        <div className="mt-10 flex h-36 items-end gap-2.5 border-b border-line" role="img" aria-label={t("landing.hero.chartLabel")}>
          {LIBRARY_MIX.map((item, i) => (
            <div key={item.key} className="relative flex h-full flex-1 flex-col justify-end">
              {i === 0 && (
                <span className="absolute -top-1 left-1/2 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md bg-invert px-2 py-1 text-xs text-on-invert">
                  {num(item.count)}
                </span>
              )}
              <div
                className={`rounded-[10px] ${i === 0 ? "bg-leaf" : "bg-[repeating-linear-gradient(135deg,var(--line)_0_3px,transparent_3px_6px)] ring-1 ring-inset ring-line"}`}
                style={{ height: `${Math.max(8, (item.count / max) * 100)}%` }}
              />
            </div>
          ))}
        </div>
        <div className="mt-2 flex gap-2.5">
          {LIBRARY_MIX.map((item) => (
            <span key={item.key} className="flex-1 truncate text-center text-[11px] text-muted">
              {t(`landing.mix.${item.key}`)}
            </span>
          ))}
        </div>
      </div>
      <div className={caption}>
        <span className={chip}>
          <Icon name="file" size={19} />
        </span>
        <div className="min-w-0 text-sm">
          <p className="truncate font-medium text-ink">{t("landing.hero.citationAct")}</p>
          <p className="truncate text-muted">{t("landing.hero.citationExample")}</p>
        </div>
      </div>
    </>
  );
}

function LanguagesSlide() {
  const { t } = useTranslation();
  const { num } = useFormat();
  const { language } = usePrefs();
  return (
    <>
      <div className={card}>
        <CardHeader value={num(LANGUAGES.length)} badge={t("landing.showcase.languagesBadge")} title={t("landing.showcase.languagesTitle")} />
        <ul className="mt-6 flex flex-wrap gap-2">
          {LANGUAGES.map((lang) => (
            <li
              key={lang.code}
              lang={lang.code}
              className={`rounded-full px-3 py-1.5 text-sm ${lang.code === language ? "bg-leaf text-white dark:text-[#11130f]" : "bg-stone text-ink"}`}
            >
              {lang.name}
            </li>
          ))}
        </ul>
      </div>
      <div className={caption}>
        <span className={chip}>
          <Icon name="mic" size={19} />
        </span>
        <div className="min-w-0 text-sm">
          <p className="font-medium text-ink">{t("landing.showcase.languagesCaption")}</p>
          <p className="text-muted">{t("landing.showcase.languagesCaptionSub")}</p>
        </div>
      </div>
    </>
  );
}

function CheckSlide() {
  const { t } = useTranslation();
  const { num } = useFormat();
  return (
    <>
      <div className={card}>
        <CardHeader value={`${num(88)}%`} badge={t("landing.showcase.checkBadge")} title={t("landing.showcase.checkTitle")} />
        <ul className="mt-5 space-y-2.5">
          {EXAMPLE_CLAIMS.map((claim) => (
            <li key={claim.key} className="flex items-start gap-3 rounded-[12px] bg-stone px-3 py-2.5 text-sm">
              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-leaf text-white dark:text-[#11130f]">
                <Icon name="check" size={12} strokeWidth={2.6} />
              </span>
              <span className="min-w-0 flex-1 leading-snug text-ink">{t(`landing.showcase.${claim.key}`)}</span>
              <span className="shrink-0 rounded-md bg-sheet px-1.5 py-0.5 font-mono text-xs text-ink-2">§ {num(claim.section)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className={caption}>
        <span className={chip}>
          <Icon name="checks" size={19} />
        </span>
        <div className="min-w-0 text-sm">
          <p className="font-medium text-ink">{t("chat.checkedAgainst", { count: 5, n: num(5) })}</p>
          <p className="truncate text-muted">{t("landing.hero.citationAct")}</p>
        </div>
      </div>
    </>
  );
}

const SLIDES = [LibrarySlide, LanguagesSlide, CheckSlide];

export default function HeroShowcase() {
  const { t } = useTranslation();
  const { num } = useFormat();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false); // user pressed pause
  const [holding, setHolding] = useState(false); // hover or keyboard focus inside
  const reducedMotion = useRef(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const swipeStart = useRef(null);

  const go = useCallback((step) => setIndex((i) => (i + step + SLIDES.length) % SLIDES.length), []);

  useEffect(() => {
    if (paused || holding || reducedMotion.current) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") go(1);
    }, INTERVAL_MS);
    return () => clearInterval(timer);
  }, [paused, holding, go]);

  const control =
    "grid h-10 w-10 place-items-center rounded-full bg-sheet/90 text-ink shadow-md backdrop-blur transition hover:bg-sheet disabled:opacity-40";

  return (
    <section
      aria-roledescription="carousel"
      aria-label={t("landing.showcase.label")}
      className="flex w-[min(100%,400px)] flex-col items-center gap-4"
      onMouseEnter={() => setHolding(true)}
      onMouseLeave={() => setHolding(false)}
      onFocus={() => setHolding(true)}
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setHolding(false)}
      onPointerDown={(e) => (swipeStart.current = e.clientX)}
      onPointerUp={(e) => {
        if (swipeStart.current == null) return;
        const dx = e.clientX - swipeStart.current;
        swipeStart.current = null;
        if (Math.abs(dx) > 40) go(dx < 0 ? 1 : -1);
      }}
    >
      {/* Every slide shares one grid cell, so the box keeps the tallest
          slide's height and nothing below it jumps between slides. */}
      <div className="grid w-full touch-pan-y select-none">
        {SLIDES.map((Slide, i) => {
          const active = i === index;
          return (
            <div
              key={i}
              role="group"
              aria-roledescription="slide"
              aria-label={t("landing.showcase.slide", { n: num(i + 1), total: num(SLIDES.length) })}
              aria-hidden={!active}
              inert={active ? undefined : ""}
              className={`col-start-1 row-start-1 flex flex-col justify-center gap-3 transition duration-500 ease-out ${
                active ? "translate-x-0 opacity-100" : `pointer-events-none opacity-0 ${i < index ? "-translate-x-6" : "translate-x-6"}`
              }`}
            >
              <Slide />
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        <button type="button" onClick={() => go(-1)} aria-label={t("landing.showcase.prev")} className={control}>
          <Icon name="arrowLeft" size={17} />
        </button>
        <div className="flex items-center gap-1.5 rounded-full bg-sheet/90 px-3 py-3 shadow-md backdrop-blur">
          {SLIDES.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setIndex(i)}
              aria-label={t("landing.showcase.slide", { n: num(i + 1), total: num(SLIDES.length) })}
              aria-current={i === index}
              className={`h-2 rounded-full transition-all ${i === index ? "w-6 bg-ink" : "w-2 bg-ink/25 hover:bg-ink/50"}`}
            />
          ))}
        </div>
        <button type="button" onClick={() => go(1)} aria-label={t("landing.showcase.next")} className={control}>
          <Icon name="arrowRight" size={17} />
        </button>
        {!reducedMotion.current && (
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            aria-label={paused ? t("landing.showcase.play") : t("landing.showcase.pause")}
            className={control}
          >
            <Icon name={paused ? "play" : "pause"} size={15} />
          </button>
        )}
      </div>
    </section>
  );
}
