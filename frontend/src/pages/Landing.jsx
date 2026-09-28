import { useTranslation } from "react-i18next";
import Icon from "../components/Icon";
import { useOpenPolicy } from "../components/PolicyDialog";
import { SiteFooter, SiteHeader } from "../components/SiteChrome";
import { ArrowButton } from "../components/ui";
import HeroShowcase from "./HeroShowcase";
import { useFormat } from "../lib/format";
import { Link, useRouter } from "../lib/router";

const TOPICS = [
  { key: "work", icon: "briefcase" },
  { key: "home", icon: "home" },
  { key: "police", icon: "shield" },
  { key: "consumer", icon: "bag" },
];

const SOURCE_ACTS = ["rti", "consumer", "bns", "wages", "dv"];

const panel = "rounded-[22px] md:rounded-[var(--radius-panel)]";

function useAsk() {
  const { navigate } = useRouter();
  return (prompt) => navigate("/chat", { state: prompt ? { prompt } : null });
}

// ── Hero ──────────────────────────────────────────────────────────────────

function Hero() {
  const { t } = useTranslation();
  const { num } = useFormat();
  const ask = useAsk();
  return (
    <section className="grid gap-2.5 md:gap-3 lg:grid-cols-2">
      <div className={`${panel} flex min-h-[560px] flex-col justify-center bg-lime px-6 py-14 text-on-lime md:px-14 lg:min-h-[640px]`}>
        <h1 className="display animate-rise max-w-[12ch] text-[44px] sm:text-[58px] xl:text-[70px]">{t("landing.hero.title")}</h1>
        <p className="animate-rise mt-6 max-w-[34rem] text-[16px] leading-relaxed text-[#2c3027] [animation-delay:80ms] md:text-[17px]">
          {t("landing.hero.body")}
        </p>
        <div className="animate-rise mt-9 flex flex-wrap gap-3 [animation-delay:140ms]">
          <button
            type="button"
            onClick={() => ask()}
            className="group inline-flex min-h-12 items-center gap-3 rounded-full bg-[#11130f] py-1.5 pl-6 pr-1.5 text-left text-[15px] font-medium leading-snug text-white transition hover:opacity-90"
          >
            {t("landing.hero.primary")}
            <span className="grid h-9 w-9 place-items-center rounded-full bg-white text-[#11130f] transition-transform group-hover:rotate-45">
              <Icon name="arrowUpRight" size={17} strokeWidth={2} />
            </span>
          </button>
          <Link
            to="/library"
            className="group inline-flex min-h-12 items-center gap-3 rounded-full border border-[#11130f] py-1.5 pl-6 pr-1.5 text-left text-[15px] font-medium leading-snug transition hover:bg-black/5"
          >
            {t("landing.hero.secondary")}
            <span className="grid h-9 w-9 place-items-center rounded-full bg-white text-[#11130f] transition-transform group-hover:rotate-45">
              <Icon name="arrowUpRight" size={17} strokeWidth={2} />
            </span>
          </Link>
        </div>

        <div className="animate-rise mt-10 flex items-center gap-3 [animation-delay:200ms]">
          <div className="flex -space-x-2" aria-hidden="true">
            {["अ", "অ", "அ"].map((glyph) => (
              <span key={glyph} className="grid h-9 w-9 place-items-center rounded-full border-2 border-lime bg-white text-sm text-[#11130f]">
                {glyph}
              </span>
            ))}
            <span className="grid h-9 w-9 place-items-center rounded-full border-2 border-lime bg-[#3d9414] text-xs font-medium text-white">+{num(8)}</span>
          </div>
          <div className="text-sm leading-tight">
            <p className="font-medium">{t("landing.hero.languagesTitle")}</p>
            <p className="text-[#3a3f35]">{t("landing.hero.languagesBody")}</p>
          </div>
        </div>
      </div>

      <div className={`${panel} relative min-h-[520px] overflow-hidden lg:min-h-0`}>
        <img src="/images/arches.webp" alt="" className="absolute inset-0 h-full w-full object-cover" fetchpriority="high" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/25 via-transparent to-transparent" />
        <div className="relative flex h-full flex-col items-center justify-center p-5 md:p-10">
          <HeroShowcase />
        </div>
      </div>
    </section>
  );
}

// ── Source strip ──────────────────────────────────────────────────────────

function SourceStrip() {
  const { t } = useTranslation();
  return (
    <section className={`${panel} bg-stone px-6 py-12 text-center md:py-14`}>
      <p className="text-[17px] text-ink-2">{t("landing.sources.lead")}</p>
      <ul className="mx-auto mt-7 flex max-w-6xl flex-wrap items-center justify-center gap-x-8 gap-y-4">
        {SOURCE_ACTS.map((act) => (
          <li key={act} className="flex items-center gap-2 text-[15px] font-medium text-ink/70">
            <Icon name="book" size={18} />
            {t(`landing.sources.acts.${act}`)}
          </li>
        ))}
        <li>
          <Link to="/library" className="text-[15px] font-medium text-ink underline decoration-lime-strong decoration-2 underline-offset-4">
            {t("landing.sources.more")}
          </Link>
        </li>
      </ul>
    </section>
  );
}

// ── Topics ────────────────────────────────────────────────────────────────

function Topics() {
  const { t } = useTranslation();
  const ask = useAsk();
  return (
    <section className={`${panel} bg-mist px-5 py-16 md:px-14 md:py-24`}>
      <p className="display mx-auto max-w-4xl text-center text-[26px] !leading-[1.25] md:text-[36px]">{t("landing.topics.lead")}</p>
      <div className="mt-14 grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TOPICS.map((topic, i) => (
          <button
            key={topic.key}
            type="button"
            onClick={() => ask(t(`landing.topics.${topic.key}.prompt`))}
            style={{ "--step": `${i * 80}px` }}
            className="group flex min-h-[200px] flex-col justify-between rounded-[18px] lg:min-h-[250px] bg-sheet p-5 text-left transition hover:-translate-y-1 hover:shadow-xl lg:mt-[var(--step)]"
          >
            <span className="grid h-11 w-11 place-items-center rounded-[12px] bg-lime text-on-lime">
              <Icon name={topic.icon} size={20} />
            </span>
            <span>
              <span className="block text-[20px] font-medium leading-snug text-ink">{t(`landing.topics.${topic.key}.title`)}</span>
              <span className="mt-2 block text-sm leading-relaxed text-muted">{t(`landing.topics.${topic.key}.body`)}</span>
              <span className="mt-4 flex items-center gap-1.5 text-sm font-medium text-ink opacity-70 transition group-hover:opacity-100">
                {t("landing.topics.askThis")}
                <Icon name="arrowRight" size={15} className="transition group-hover:translate-x-0.5" />
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

// ── Process ───────────────────────────────────────────────────────────────

function Process() {
  const { t } = useTranslation();
  const { num } = useFormat();
  return (
    <section id="how" className={`${panel} bg-sheet px-5 py-16 ring-1 ring-inset ring-line md:px-14 md:py-24`}>
      <div className="grid gap-12 xl:grid-cols-[1.45fr_1fr]">
        <div>
          <h2 className="display max-w-[16ch] text-[36px] md:text-[48px]">{t("landing.process.title")}</h2>
          <ol className="mt-14 grid gap-10 md:grid-cols-3 md:gap-0">
            {[1, 2, 3].map((n, i) => (
              <li
                key={n}
                style={{ "--offset": `${i * 2.25}rem` }}
                className={`md:px-7 md:pt-[var(--offset)] md:first:pl-0 ${i > 0 ? "md:border-l md:border-ink/15" : ""}`}
              >
                <p className="text-sm font-medium tracking-wide text-muted">{t("landing.process.step", { n: num(n) })}</p>
                <span className="mt-3 flex flex-col items-start" aria-hidden="true">
                  <span className="h-5 w-px bg-ink/30" />
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-invert">
                    <span className="h-2 w-2 rounded-full bg-lime" />
                  </span>
                </span>
                <h3 className="mt-5 text-[21px] font-medium leading-snug">{t(`landing.process.s${n}Title`)}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{t(`landing.process.s${n}Body`)}</p>
              </li>
            ))}
          </ol>
        </div>
        <div className="grid min-h-[420px] grid-cols-2 gap-3">
          <img src="/images/network.webp" alt="" loading="lazy" className="h-full w-full rounded-[18px] object-cover" />
          <div className="grid gap-3">
            <img src="/images/books.webp" alt="" loading="lazy" className="h-full w-full rounded-[18px] object-cover" />
            <img src="/images/brief.webp" alt="" loading="lazy" className="h-full w-full rounded-[18px] object-cover" />
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Numbers ───────────────────────────────────────────────────────────────

const NUMBERS = [
  { key: "documents", value: 494, image: "arches" },
  { key: "passages", value: 72771, image: "books" },
  { key: "languages", value: 11, image: "brief" },
  { key: "citations", value: 4.6, image: "network" },
];

function Numbers() {
  const { t } = useTranslation();
  const { num } = useFormat();
  return (
    <section className={`${panel} bg-stone px-5 py-16 md:px-14 md:py-24`}>
      <h2 className="display mx-auto max-w-[18ch] text-center text-[36px] md:text-[48px]">{t("landing.numbers.title")}</h2>
      <dl className="mx-auto mt-14 max-w-6xl">
        {NUMBERS.map((row, i) => (
          <div key={row.key} className="grid grid-cols-[1fr_auto] items-center gap-x-6 gap-y-3 border-b border-ink/10 py-8 md:grid-cols-12 md:py-6">
            <dt className="text-[15px] text-ink md:col-span-3">{t(`landing.numbers.${row.key}.label`)}</dt>
            <dd className="text-right text-[44px] font-medium leading-none tracking-[-0.03em] md:col-span-4 md:text-[64px]">{num(row.value)}</dd>
            <dd className="hidden justify-center md:col-span-2 md:flex" aria-hidden="true">
              <img
                src={`/images/${row.image}.webp`}
                alt=""
                loading="lazy"
                className={`h-28 w-28 rounded-[14px] object-cover shadow-md ${i % 2 ? "rotate-[5deg]" : "-rotate-[6deg]"}`}
              />
            </dd>
            <dd className="col-span-2 text-[15px] leading-relaxed text-ink-2 md:col-span-3">{t(`landing.numbers.${row.key}.body`)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// ── Features ──────────────────────────────────────────────────────────────

const FEATURES = [
  { key: "deep", icon: "sparkle" },
  { key: "pdf", icon: "download" },
  { key: "history", icon: "refresh" },
  { key: "voice", icon: "mic" },
];

function Features() {
  const { t } = useTranslation();
  return (
    <section className={`${panel} bg-mist px-5 py-16 md:px-14 md:py-24`}>
      <div className="grid items-center gap-12 lg:grid-cols-2">
        <div>
          <h2 className="display max-w-[16ch] text-[36px] md:text-[48px]">{t("landing.features.title")}</h2>
          <p className="mt-5 max-w-xl text-[16px] leading-relaxed text-ink-2">{t("landing.features.body")}</p>
          <ul className="mt-10 space-y-6">
            {FEATURES.map((f) => (
              <li key={f.key} className="flex gap-4">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-invert text-on-invert">
                  <Icon name={f.icon} size={18} />
                </span>
                <span>
                  <span className="block font-medium">{t(`landing.features.${f.key}.title`)}</span>
                  <span className="mt-1 block text-[15px] leading-relaxed text-ink-2">{t(`landing.features.${f.key}.body`)}</span>
                </span>
              </li>
            ))}
          </ul>
          <ArrowButton to="/chat" className="mt-10">{t("landing.features.cta")}</ArrowButton>
        </div>
        <div className="relative">
          <img src="/images/brief.webp" alt="" loading="lazy" className="aspect-square w-full rounded-[22px] object-cover" />
          <div className="absolute bottom-5 left-5 right-5 rounded-[16px] bg-sheet/95 p-4 shadow-lg backdrop-blur sm:right-auto sm:w-80">
            <p className="text-xs uppercase tracking-wider text-muted">{t("landing.features.pdfCardEyebrow")}</p>
            <p className="mt-1 font-medium">{t("landing.features.pdfCardTitle")}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {["question", "answer", "sources", "match"].map((part) => (
                <span key={part} className="rounded-full bg-stone px-2.5 py-1 text-xs text-ink-2">
                  {t(`landing.features.pdfParts.${part}`)}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Limits ────────────────────────────────────────────────────────────────

function Limits() {
  const { t } = useTranslation();
  const openPolicy = useOpenPolicy();
  return (
    <section className={`${panel} bg-lime px-5 py-16 text-on-lime md:px-14 md:py-24`}>
      <h2 className="display max-w-[20ch] text-[36px] md:text-[48px]">{t("landing.limits.title")}</h2>
      <div className="mt-12 grid gap-10 lg:grid-cols-[1fr_1.1fr] lg:gap-16">
        <img src="/images/books.webp" alt="" loading="lazy" className="aspect-[4/3] w-full rounded-[20px] object-cover" />
        <div className="flex flex-col">
          <ul className="divide-y divide-black/15 border-y border-black/15">
            {[1, 2, 3, 4].map((n) => (
              <li key={n} className="py-5">
                <p className="font-medium">{t(`landing.limits.l${n}Title`)}</p>
                <p className="mt-1 text-[15px] leading-relaxed text-[#3a3f35]">{t(`landing.limits.l${n}Body`)}</p>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => openPolicy("disclaimer")}
            className="group mt-8 inline-flex min-h-12 max-w-full items-center gap-3 rounded-full bg-[#11130f] py-1.5 pl-6 pr-1.5 text-left text-[15px] font-medium leading-snug text-white transition hover:opacity-90"
          >
            {t("landing.limits.cta")}
            <span className="grid h-9 w-9 place-items-center rounded-full bg-white text-[#11130f] transition-transform group-hover:rotate-45">
              <Icon name="arrowUpRight" size={17} strokeWidth={2} />
            </span>
          </button>
        </div>
      </div>
    </section>
  );
}

// ── FAQ ───────────────────────────────────────────────────────────────────

const FAQ_COUNT = 8;

function Faq() {
  const { t } = useTranslation();
  const items = Array.from({ length: FAQ_COUNT }, (_, i) => i + 1);
  const columns = [items.filter((n) => n % 2), items.filter((n) => !(n % 2))];
  return (
    <section id="faq" className={`${panel} bg-stone px-5 py-16 md:px-14 md:py-24`}>
      <h2 className="display mx-auto max-w-[18ch] text-center text-[36px] md:text-[48px]">{t("landing.faq.title")}</h2>
      <div className="mx-auto mt-12 grid max-w-6xl gap-3 md:grid-cols-2">
        {columns.map((column, c) => (
          <div key={c} className="space-y-3">
            {column.map((n) => (
              <details key={n} className="group rounded-[16px] bg-sheet px-5 open:pb-5">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-5 text-[15px] font-medium [&::-webkit-details-marker]:hidden">
                  {t(`landing.faq.q${n}`)}
                  <Icon name="chevronDown" size={18} className="text-muted transition group-open:rotate-180" />
                </summary>
                <p className="text-[15px] leading-relaxed text-ink-2">{t(`landing.faq.a${n}`)}</p>
              </details>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Closing call to action ────────────────────────────────────────────────

function FinalCta() {
  const { t } = useTranslation();
  const ask = useAsk();
  return (
    <section className={`${panel} relative overflow-hidden`}>
      <img src="/images/arches.webp" alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-b from-black/55 via-black/45 to-black/70" />
      <div className="relative mx-auto flex max-w-3xl flex-col items-center px-5 py-24 text-center text-white md:py-32">
        <h2 className="display text-[38px] md:text-[56px]">{t("landing.cta.title")}</h2>
        <p className="mt-5 max-w-xl text-[16px] leading-relaxed text-white/85">{t("landing.cta.body")}</p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <ArrowButton variant="lime" onClick={() => ask()}>{t("landing.cta.primary")}</ArrowButton>
          <ArrowButton variant="glass" to="/library">{t("landing.cta.secondary")}</ArrowButton>
        </div>
        <ul className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm text-white/90">
          {["t1", "t2", "t3"].map((k) => (
            <li key={k} className="flex items-center gap-2">
              <Icon name="checks" size={17} />
              {t(`landing.cta.${k}`)}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-page">
      <div className="mx-auto max-w-[1440px] px-2 pt-2 md:px-4 md:pt-4">
        <div className="rounded-[26px] bg-sheet md:rounded-[34px]">
          <SiteHeader />
          <main className="flex flex-col gap-2.5 p-2.5 pt-0 md:gap-3 md:p-3 md:pt-0">
            <Hero />
            <SourceStrip />
            <Topics />
            <Process />
            <Numbers />
            <Features />
            <Limits />
            <Faq />
            <FinalCta />
          </main>
        </div>
      </div>
      <SiteFooter />
    </div>
  );
}
