import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../../components/Icon";
import { IconButton, Logo } from "../../components/ui";
import { GUEST_ANSWER_LIMIT, useAuth } from "../../context/AuthContext";
import { useChat } from "../../context/ChatContext";
import { useFormat } from "../../lib/format";
import { Link } from "../../lib/router";

const DAY = 24 * 60 * 60 * 1000;

function groupByAge(sessions) {
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const groups = { today: [], week: [], older: [] };
  [...sessions]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .forEach((s) => {
      if (s.updatedAt >= startOfToday) groups.today.push(s);
      else if (s.updatedAt >= startOfToday - 6 * DAY) groups.week.push(s);
      else groups.older.push(s);
    });
  return groups;
}

function ChatRow({ session, active, busy, onSelect, onDelete }) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);

  return (
    <li className="group relative">
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "page" : undefined}
        className={`flex w-full items-center gap-2 rounded-[12px] py-2.5 pl-3 pr-10 text-left text-sm transition ${
          active ? "bg-sheet text-ink shadow-sm" : "text-ink-2 hover:bg-sheet/60 hover:text-ink"
        }`}
      >
        {busy && <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-leaf" aria-label={t("chat.working")} />}
        <span className="truncate">{session.title || t("chat.untitled")}</span>
      </button>
      {confirming ? (
        <span className="absolute inset-y-1 right-1 flex items-center gap-1 rounded-[10px] bg-sheet pl-2 shadow-sm">
          <button type="button" onClick={onDelete} className="rounded-md px-2 py-1 text-xs font-medium text-danger hover:bg-danger/10">
            {t("chat.delete")}
          </button>
          <button type="button" onClick={() => setConfirming(false)} aria-label={t("common.cancel")} className="grid h-7 w-7 place-items-center rounded-md text-muted hover:text-ink">
            <Icon name="x" size={15} />
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={t("chat.deleteChat")}
          className="absolute right-1.5 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-muted opacity-0 transition hover:bg-stone hover:text-ink focus:opacity-100 group-hover:opacity-100"
        >
          <Icon name="trash" size={16} />
        </button>
      )}
    </li>
  );
}

export default function Sidebar({ onClose, onOpenSettings }) {
  const { t } = useTranslation();
  const { user, isGuest, guestUsed, guestRemaining, signOut } = useAuth();
  const { sessions, activeId, busyIds, newChat, selectChat, deleteChat } = useChat();
  const { num } = useFormat();
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return groupByAge(q ? sessions.filter((s) => s.title.toLowerCase().includes(q)) : sessions);
  }, [sessions, query]);

  const pick = (fn) => () => {
    fn();
    if (window.matchMedia("(max-width: 1023px)").matches) onClose();
  };

  const empty = !groups.today.length && !groups.week.length && !groups.older.length;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <Link to="/" aria-label={t("nav.home")} className="rounded-lg">
          <Logo size="sm" />
        </Link>
        <IconButton icon="panel" label={t("chat.hideSidebar")} onClick={onClose} className="h-9 w-9" />
      </div>

      <div className="px-3">
        <button
          type="button"
          onClick={pick(newChat)}
          className="flex min-h-11 w-full items-center justify-between gap-2 rounded-full bg-invert py-1.5 pl-4 pr-1.5 text-left text-sm font-medium leading-snug text-on-invert transition hover:opacity-90"
        >
          {t("chat.newChat")}
          <span className="grid h-8 w-8 place-items-center rounded-full bg-on-invert text-invert">
            <Icon name="plus" size={16} strokeWidth={2.2} />
          </span>
        </button>
        {sessions.length > 3 && (
          <label className="mt-3 flex h-10 items-center gap-2 rounded-[12px] bg-sheet px-3 text-sm text-muted ring-1 ring-line focus-within:ring-ink/40">
            <Icon name="search" size={16} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("chat.searchChats")}
              aria-label={t("chat.searchChats")}
              className="w-full bg-transparent text-ink outline-none placeholder:text-muted"
            />
          </label>
        )}
      </div>

      <nav aria-label={t("chat.history")} className="thin-scrollbar mt-4 flex-1 overflow-y-auto px-3">
        {empty ? (
          <p className="px-3 py-2 text-sm leading-relaxed text-muted">{query ? t("chat.noMatches") : t("chat.noChats")}</p>
        ) : (
          ["today", "week", "older"].map(
            (key) =>
              groups[key].length > 0 && (
                <section key={key} className="mb-5">
                  <h3 className="mb-1.5 px-3 text-xs font-medium text-muted">{t(`chat.group.${key}`)}</h3>
                  <ul className="space-y-0.5">
                    {groups[key].map((s) => (
                      <ChatRow
                        key={s.id}
                        session={s}
                        active={s.id === activeId}
                        busy={!!busyIds[s.id]}
                        onSelect={pick(() => selectChat(s.id))}
                        onDelete={() => deleteChat(s.id)}
                      />
                    ))}
                  </ul>
                </section>
              )
          )
        )}
      </nav>

      <div className="space-y-2 p-3">
        <Link to="/library" className="flex items-center gap-2.5 rounded-[12px] px-3 py-2.5 text-sm text-ink-2 transition hover:bg-sheet hover:text-ink">
          <Icon name="book" size={17} />
          {t("nav.library")}
        </Link>

        {isGuest ? (
          <div className="rounded-[16px] bg-sheet p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
              <span className="font-medium">{t("chat.guestTitle")}</span>
              <span className="text-muted">{t("chat.guestLeft", { n: num(guestRemaining), total: num(GUEST_ANSWER_LIMIT) })}</span>
            </div>
            <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-stone" role="progressbar" aria-valuemin={0} aria-valuemax={GUEST_ANSWER_LIMIT} aria-valuenow={guestUsed}>
              <div className="h-full rounded-full bg-leaf transition-all" style={{ width: `${(guestUsed / GUEST_ANSWER_LIMIT) * 100}%` }} />
            </div>
            <p className="mt-2.5 text-xs leading-relaxed text-muted">{t("chat.guestNote")}</p>
            <Link to="/signin" className="mt-3 flex min-h-10 items-center justify-center rounded-full bg-lime px-4 py-2 text-center text-sm font-medium leading-snug text-on-lime transition hover:bg-lime-strong">
              {t("chat.createAccount")}
            </Link>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-[16px] bg-sheet p-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-lime text-sm font-medium text-on-lime" aria-hidden="true">
              {(user.name || user.email).trim().charAt(0).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{user.name || user.email}</span>
              <span className="block truncate text-xs text-muted">{user.email}</span>
            </span>
            <IconButton icon="sliders" label={t("settings.title")} onClick={onOpenSettings} className="h-9 w-9" size={17} />
            <IconButton icon="logOut" label={t("settings.signOut")} onClick={signOut} className="h-9 w-9" size={17} />
          </div>
        )}
        {isGuest && (
          <button type="button" onClick={onOpenSettings} className="flex w-full items-center gap-2.5 rounded-[12px] px-3 py-2.5 text-sm text-ink-2 transition hover:bg-sheet hover:text-ink">
            <Icon name="sliders" size={17} />
            {t("settings.title")}
          </button>
        )}
      </div>
    </div>
  );
}
