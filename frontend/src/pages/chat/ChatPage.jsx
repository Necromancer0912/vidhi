import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../../components/Icon";
import { LanguageMenu, ThemeToggle } from "../../components/Preferences";
import { IconButton } from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import { useChat } from "../../context/ChatContext";
import { Link, useRouter } from "../../lib/router";
import Composer from "./Composer";
import { BotMessage, UserMessage } from "./Message";
import SettingsDialog from "./SettingsDialog";
import Sidebar from "./Sidebar";

const STARTERS = [
  { key: "work", icon: "briefcase" },
  { key: "home", icon: "home" },
  { key: "police", icon: "shield" },
  { key: "consumer", icon: "bag" },
];

const LONG_CHAT_TURNS = 7;

function Greeting() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { send } = useChat();
  const hour = new Date().getHours();
  const part = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
  const firstName = user?.name?.trim().split(/\s+/)[0];

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-8 pt-10 md:pt-20">
      <h1 className="display animate-rise text-[34px] md:text-[46px]">
        {firstName ? t(`chat.greeting.${part}Named`, { name: firstName }) : t(`chat.greeting.${part}`)}
      </h1>
      <p className="animate-rise mt-3 max-w-xl text-[16px] leading-relaxed text-ink-2 [animation-delay:60ms]">{t("chat.intro")}</p>
      <div className="mt-10 grid gap-3 sm:grid-cols-2">
        {STARTERS.map((s, i) => (
          <button
            key={s.key}
            type="button"
            onClick={() => send(t(`landing.topics.${s.key}.prompt`), { fresh: true })}
            style={{ animationDelay: `${100 + i * 50}ms` }}
            className="animate-rise group flex items-start gap-4 rounded-[18px] bg-stone p-4 text-left transition hover:bg-line"
          >
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[11px] bg-lime text-on-lime">
              <Icon name={s.icon} size={18} />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-ink">{t(`landing.topics.${s.key}.title`)}</span>
              <span className="mt-1 block text-sm leading-snug text-muted">{t(`landing.topics.${s.key}.prompt`)}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Conversation({ chat }) {
  const { t } = useTranslation();
  const { newChat } = useChat();
  const endRef = useRef(null);
  const scroller = useRef(null);
  const pinned = useRef(true);

  // Follow new tokens only while the reader is already at the bottom.
  const onScroll = () => {
    const el = scroller.current;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };
  useLayoutEffect(() => {
    if (pinned.current) endRef.current?.scrollIntoView({ block: "end" });
  }, [chat.messages]);
  useEffect(() => {
    pinned.current = true;
    endRef.current?.scrollIntoView({ block: "end" });
  }, [chat.id]);

  const userTurns = chat.messages.filter((m) => m.role === "user").length;

  return (
    <div ref={scroller} onScroll={onScroll} className="thin-scrollbar flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl space-y-8 px-4 pb-6 pt-8">
        {chat.messages.map((m, i) => {
          if (m.role === "user") return <UserMessage key={m.id} message={m} />;
          const question = [...chat.messages.slice(0, i)].reverse().find((x) => x.role === "user")?.text || "";
          return <BotMessage key={m.id} message={m} question={question} />;
        })}
        {userTurns >= LONG_CHAT_TURNS && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[14px] bg-stone px-4 py-3 text-sm text-ink-2">
            <Icon name="alert" size={16} />
            <span className="flex-1">{t("chat.longChat")}</span>
            <button type="button" onClick={newChat} className="font-medium text-ink underline underline-offset-4">
              {t("chat.newChat")}
            </button>
          </p>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { t } = useTranslation();
  const { isGuest } = useAuth();
  const { activeChat, send } = useChat();
  const { state, clearState } = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // A question handed over from the landing page or library: send it once,
  // even when StrictMode runs this effect twice.
  const handled = useRef(null);
  useEffect(() => {
    if (state?.prompt && handled.current !== state) {
      handled.current = state;
      send(state.prompt, { fresh: true });
      clearState();
    }
  }, [state, send, clearState]);

  return (
    <div className="flex h-dvh gap-2.5 bg-page lg:p-2.5">
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-[288px] bg-stone transition-transform duration-300 lg:static lg:z-auto lg:shrink-0 lg:rounded-[22px] ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:hidden"
        }`}
        aria-label={t("chat.history")}
      >
        <Sidebar onClose={() => setSidebarOpen(false)} onOpenSettings={() => setSettingsOpen(true)} />
      </aside>

      <main className="flex min-w-0 flex-1 flex-col bg-sheet lg:rounded-[22px]">
        <header className="flex h-16 shrink-0 items-center gap-2 border-b border-line px-3 md:px-4">
          {!sidebarOpen && <IconButton icon="panel" label={t("chat.showSidebar")} onClick={() => setSidebarOpen(true)} />}
          <h1 className="min-w-0 flex-1 truncate text-[15px] font-medium">{activeChat?.title || t("chat.newChat")}</h1>
          <LanguageMenu compact />
          <ThemeToggle />
          {isGuest && (
            <Link to="/signin" className="ml-1 hidden h-10 items-center rounded-full bg-invert px-4 text-sm font-medium text-on-invert sm:flex">
              {t("nav.signIn")}
            </Link>
          )}
        </header>

        {activeChat?.messages.length ? (
          <Conversation chat={activeChat} />
        ) : (
          <div className="thin-scrollbar flex-1 overflow-y-auto">
            <Greeting />
          </div>
        )}

        <div className="mx-auto w-full max-w-3xl shrink-0 px-3 pb-3 md:px-4 md:pb-4">
          <Composer />
        </div>
      </main>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
