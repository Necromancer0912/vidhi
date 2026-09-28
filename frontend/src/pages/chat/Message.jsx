import { memo, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../../components/Icon";
import { useChat } from "../../context/ChatContext";
import { useToast } from "../../context/ToastContext";
import { Link } from "../../lib/router";
import { useDocumentTitle } from "../../lib/documents";
import { formatDate, useFormat } from "../../lib/format";
import { renderMarkdown, safeHttpUrl } from "../../lib/markdown";

function useTime(at) {
  const { time } = useFormat();
  return useMemo(() => (at ? time(at) : ""), [at, time]);
}

export function UserMessage({ message }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-[20px] rounded-br-[6px] bg-stone px-4 py-3 text-[15px] leading-relaxed text-ink md:max-w-[75%]">
        {message.text}
      </p>
    </div>
  );
}

function Stage({ message }) {
  const { t } = useTranslation();
  const label =
    message.stage === "deep" && message.stageDetail
      ? t("chat.stage.deepDetail", { query: message.stageDetail })
      : t(`chat.stage.${message.stage || "searching"}`);
  return (
    <p className="flex items-center gap-2 text-sm text-muted" aria-live="polite">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-leaf" style={{ animationDelay: `${i * 150}ms` }} />
        ))}
      </span>
      {label}
    </p>
  );
}

function Sources({ citations }) {
  const { t } = useTranslation();
  const { num } = useFormat();
  const docTitle = useDocumentTitle();
  const [open, setOpen] = useState(false);
  if (!citations?.length) return null;
  const shown = open ? citations : citations.slice(0, 3);

  return (
    <div className="mt-5">
      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("chat.sources")}</p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {shown.map((c, i) => {
          const url = safeHttpUrl(c.source_url);
          const content = (
            <>
              <span className="flex items-start justify-between gap-2">
                <span className="line-clamp-2 text-sm font-medium text-ink">{c.document_title ? docTitle(c.document_title) : t("chat.untitledSource")}</span>
                {url && <Icon name="external" size={14} className="mt-0.5 text-muted" />}
              </span>
              {c.section && <span className="mt-1.5 block truncate font-mono text-xs text-ink-2">§ {c.section}</span>}
            </>
          );
          return (
            <li key={`${c.chunk_id || i}`}>
              {url ? (
                <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="block h-full rounded-[14px] bg-stone p-3 transition hover:bg-line">
                  {content}
                </a>
              ) : (
                <div className="h-full rounded-[14px] bg-stone p-3">{content}</div>
              )}
            </li>
          );
        })}
      </ul>
      {citations.length > 3 && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="mt-2 text-sm font-medium text-ink-2 underline underline-offset-4 hover:text-ink">
          {open ? t("chat.fewerSources") : t("chat.allSources", { n: num(citations.length) })}
        </button>
      )}
    </div>
  );
}

function Actions({ message, question }) {
  const { t } = useTranslation();
  const { lang, num } = useFormat();
  const docTitle = useDocumentTitle();
  const toast = useToast();
  const { rate } = useChat();
  const [exporting, setExporting] = useState(false);
  const confidence = message.meta?.confidence;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.text);
      toast(t("chat.copied"));
    } catch {
      toast(t("chat.copyFailed"), "error");
    }
  };

  const download = async () => {
    setExporting(true);
    try {
      const { exportAnswerPdf } = await import("../../lib/exportPdf");
      await exportAnswerPdf({
        question,
        answer: message.text,
        sources: (message.meta?.citations || []).map((c) => ({ ...c, document_title: docTitle(c.document_title) })),
        confidence,
        lang,
        pageLabel: (n, total) => t("pdf.page", { n: num(n), total: num(total) }),
        labels: {
          title: t("pdf.title"),
          date: formatDate(new Date(), lang),
          question: t("pdf.question"),
          answer: t("pdf.answer"),
          sources: t("pdf.sources"),
          match: confidence == null ? "" : t("chat.match", { value: num(Math.round(confidence * 100)) }),
          disclaimer: t("pdf.disclaimer"),
        },
      });
    } catch {
      toast(t("chat.pdfFailed"), "error");
    } finally {
      setExporting(false);
    }
  };

  const button = "flex h-9 items-center gap-1.5 rounded-full px-3 text-sm text-ink-2 transition hover:bg-stone hover:text-ink disabled:opacity-50";
  return (
    <div className="mt-4 flex flex-wrap items-center gap-1 border-t border-line pt-3">
      <button type="button" onClick={copy} className={button}>
        <Icon name="copy" size={16} />
        {t("chat.copy")}
      </button>
      <button type="button" onClick={download} disabled={exporting} className={button}>
        <Icon name="download" size={16} />
        {exporting ? t("chat.preparingPdf") : t("chat.downloadPdf")}
      </button>
      <span className="ml-auto flex items-center gap-1">
        {message.feedback ? (
          <span className="px-2 text-sm text-muted">{t("chat.thanks")}</span>
        ) : (
          <>
            <button type="button" onClick={() => rate(message.id, true)} aria-label={t("chat.helpful")} title={t("chat.helpful")} className={`${button} w-9 justify-center px-0`}>
              <Icon name="thumbUp" size={16} />
            </button>
            <button type="button" onClick={() => rate(message.id, false)} aria-label={t("chat.notHelpful")} title={t("chat.notHelpful")} className={`${button} w-9 justify-center px-0`}>
              <Icon name="thumbDown" size={16} />
            </button>
          </>
        )}
      </span>
    </div>
  );
}

function Badges({ meta }) {
  const { t } = useTranslation();
  const { num } = useFormat();
  const pills = [];
  if (meta.citations?.length) {
    pills.push(
      <span key="src" className="flex items-center gap-1.5 rounded-full bg-leaf/12 px-3 py-1 text-xs font-medium text-leaf">
        <Icon name="check" size={13} strokeWidth={2.4} />
        {t("chat.checkedAgainst", { count: meta.citations.length, n: num(meta.citations.length) })}
      </span>
    );
  }
  if (typeof meta.confidence === "number") {
    pills.push(
      <span key="match" title={t("chat.matchExplain")} className="cursor-help rounded-full bg-stone px-3 py-1 text-xs text-ink-2">
        {t("chat.match", { value: num(Math.round(meta.confidence * 100)) })}
      </span>
    );
  }
  if (meta.retries > 0) pills.push(<span key="rev" className="rounded-full bg-stone px-3 py-1 text-xs text-ink-2">{t("chat.revised", { count: meta.retries, n: num(meta.retries) })}</span>);
  if (meta.deep) pills.push(<span key="deep" className="rounded-full bg-lime px-3 py-1 text-xs text-on-lime">{t("chat.deepSearch")}</span>);
  if (meta.cached) pills.push(<span key="cache" className="rounded-full bg-stone px-3 py-1 text-xs text-ink-2">{t("chat.fromCache")}</span>);
  return pills.length ? <div className="mt-5 flex flex-wrap gap-2">{pills}</div> : null;
}

export const BotMessage = memo(function BotMessage({ message, question }) {
  const { t } = useTranslation();
  const { retry } = useChat();
  const time = useTime(message.at);
  const html = useMemo(() => renderMarkdown(message.text), [message.text]);

  return (
    <article className="group">
      <header className="mb-3 flex items-center gap-2.5 text-sm">
        <span className="grid h-7 w-7 place-items-center rounded-[8px] bg-lime text-[14px] font-semibold text-on-lime" aria-hidden="true">§</span>
        <span className="font-medium">Vidhi</span>
        {time && <time className="text-muted">{time}</time>}
      </header>

      {message.limit ? (
        <div className="rounded-[18px] bg-stone p-5">
          <p className="font-medium">{t("chat.limitTitle")}</p>
          <p className="mt-1.5 text-[15px] leading-relaxed text-ink-2">{t("chat.limitBody")}</p>
          <Link to="/signin" className="mt-4 inline-flex h-10 items-center rounded-full bg-invert px-5 text-sm font-medium text-on-invert">
            {t("chat.createAccount")}
          </Link>
        </div>
      ) : (
        <>
          {message.drafts?.length > 0 && !message.streaming && (
            <details className="mb-4 rounded-[14px] bg-stone px-4 text-sm">
              <summary className="cursor-pointer py-3 text-ink-2">{t("chat.firstDraft")}</summary>
              <p className="whitespace-pre-wrap pb-4 leading-relaxed text-muted">{message.drafts[0]}</p>
            </details>
          )}

          {message.stage === "retrying" && (
            <p className="mb-4 flex items-start gap-2 rounded-[14px] bg-amber/10 px-4 py-3 text-sm text-amber">
              <Icon name="refresh" size={16} className="mt-0.5 animate-spin [animation-duration:2s]" />
              {t("chat.retrying")}
            </p>
          )}

          {message.text ? (
            <div className={`answer ${message.streaming ? "caret" : ""}`} dangerouslySetInnerHTML={{ __html: html }} />
          ) : (
            message.streaming && <Stage message={message} />
          )}
          {message.streaming && message.text && message.stage !== "writing" && (
            <div className="mt-3">
              <Stage message={message} />
            </div>
          )}

          {(message.error || message.stopped) && (
            <div className={`mt-3 flex flex-wrap items-center gap-3 rounded-[14px] px-4 py-3 text-sm ${message.error ? "bg-danger/10 text-danger" : "bg-stone text-ink-2"}`}>
              <Icon name={message.error ? "alert" : "stop"} size={16} />
              <span className="flex-1">{message.error || t("chat.stopped")}</span>
              <button type="button" onClick={() => retry(message.id)} className="flex items-center gap-1.5 font-medium underline-offset-4 hover:underline">
                <Icon name="refresh" size={15} />
                {t("chat.tryAgain")}
              </button>
            </div>
          )}

          {!message.streaming && message.meta && !message.error && (
            <>
              <Badges meta={message.meta} />
              <Sources citations={message.meta.citations} />
            </>
          )}
          {!message.streaming && message.text && !message.error && <Actions message={message} question={question} />}
        </>
      )}
    </article>
  );
});
