import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { describeError, openChatStream, request } from "../lib/api";
import { readEventStream } from "../lib/sse";
import { useAuth } from "./AuthContext";
import { useToast } from "./ToastContext";

const ChatContext = createContext(null);

const KEEP_TURNS = 8; // recent turns sent verbatim; older ones are summarised
const MAX_SAVED_SESSIONS = 40;
const MAX_SAVE_BYTES = 1_200_000; // server refuses anything over 1.5 MB

// ── Shape helpers ─────────────────────────────────────────────────────────

// Sessions saved by earlier versions used `question`, `metadata` and
// `limitReached`; map them onto the current shape.
function normaliseMessage(m, i) {
  if (!m || (m.role !== "user" && m.role !== "bot")) return null;
  const meta = m.meta || (m.metadata && {
    confidence: m.metadata.confidence_score,
    citations: m.metadata.citations || [],
    retries: m.metadata.retry_count || 0,
    cached: !!m.metadata.cache_hit,
    deep: !!m.metadata.deep_search,
  });
  return {
    id: String(m.id || `${m.role}${i}`),
    role: m.role,
    text: typeof m.text === "string" ? m.text : "",
    at: typeof m.at === "number" ? m.at : null,
    limit: !!(m.limit || m.limitReached),
    error: typeof m.error === "string" ? m.error : null,
    stopped: !!m.stopped,
    drafts: Array.isArray(m.drafts) ? m.drafts.filter((d) => typeof d === "string") : [],
    meta: meta || null,
    feedback: m.feedback === "up" || m.feedback === "down" ? m.feedback : null,
    streaming: false,
  };
}

// Sent to the server as the conversation's session id. Random rather than the
// timestamp id, so it can't be guessed.
const newSessionId = () => crypto.randomUUID();

function normaliseSession(s) {
  if (!s || s.id == null || !Array.isArray(s.messages)) return null;
  const messages = s.messages.map(normaliseMessage).filter(Boolean);
  const firstQuestion = messages.find((m) => m.role === "user")?.text || "";
  return {
    id: s.id,
    sid: typeof s.sid === "string" && /^[A-Za-z0-9-]{16,64}$/.test(s.sid) ? s.sid : newSessionId(),
    title: (s.title || firstQuestion || s.question || "").slice(0, 80),
    messages,
    updatedAt: s.updatedAt || (typeof s.id === "number" ? s.id : Date.now()),
  };
}

function forSaving(sessions) {
  const clean = [...sessions]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_SAVED_SESSIONS)
    .map((s) => ({
      ...s,
      messages: s.messages.map(({ streaming, stage, stageDetail, ...rest }) => rest),
    }));
  while (clean.length > 1 && JSON.stringify(clean).length > MAX_SAVE_BYTES) clean.pop();
  return clean;
}

function conversationHistory(messages) {
  const turns = [];
  for (const m of messages) {
    if (m.role === "user" && m.text) turns.push({ role: "user", content: m.text.slice(0, 6000) });
    else if (m.role === "bot" && m.text && !m.error && !m.limit) turns.push({ role: "assistant", content: m.text.slice(0, 6000) });
  }
  if (turns.length <= KEEP_TURNS) return turns;

  const older = turns.slice(0, -KEEP_TURNS).map((t) => {
    const who = t.role === "user" ? "User" : "Assistant";
    const snippet = t.content.slice(0, 120).replace(/\n/g, " ");
    return `${who}: ${snippet}${t.content.length > 120 ? "…" : ""}`;
  });
  return [
    { role: "user", content: `[Earlier conversation summary]\n${older.join("\n")}`.slice(0, 6000) },
    ...turns.slice(-KEEP_TURNS),
  ];
}

// ── Provider ──────────────────────────────────────────────────────────────

export function ChatProvider({ children }) {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const { token, isGuest, guestLimitReached, recordGuestAnswer } = useAuth();

  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [busy, setBusy] = useState({});
  const [historyReady, setHistoryReady] = useState(false);

  const controllers = useRef({});
  const live = useRef({});
  live.current = { sessions, activeId, busy, token, isGuest, guestLimitReached, language: i18n.resolvedLanguage || "en" };

  // ── Load (and merge guest chats) when an account signs in ────────────────
  const previousToken = useRef(token);
  useEffect(() => {
    const wasGuest = !previousToken.current;
    previousToken.current = token;
    setHistoryReady(false);

    if (!token) {
      Object.values(controllers.current).forEach((c) => c.abort());
      if (!wasGuest) {
        setSessions([]);
        setActiveId(null);
      }
      return;
    }

    let cancelled = false;
    request("/chat/history", { token })
      .then((data) => {
        if (cancelled) return;
        const saved = (data?.sessions || []).map(normaliseSession).filter(Boolean);
        setSessions((local) => {
          const carried = wasGuest ? local.filter((s) => !saved.some((x) => x.id === s.id)) : [];
          return [...carried, ...saved];
        });
        const restore = data?.active_chat?.id;
        setActiveId((current) => current ?? (saved.some((s) => s.id === restore) ? restore : null));
        setHistoryReady(true);
      })
      .catch(() => {
        // Saving stays off so a failed load can never overwrite stored history.
        if (!cancelled) toast(t("chat.historyLoadFailed"), "error");
      });
    return () => {
      cancelled = true;
    };
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Save once the server copy has been loaded ───────────────────────────
  // While an answer streams, sessions change many times a second, so saves
  // are debounced. Otherwise (including the moment an answer finishes) save
  // right away, so a reload straight after a fast answer doesn't lose it.
  const streaming = Object.keys(busy).length > 0;
  useEffect(() => {
    if (!token || !historyReady) return;
    const timer = setTimeout(() => {
      const body = { sessions: forSaving(sessions), active_chat: activeId ? { id: activeId } : null };
      // keepalive lets the save finish even if the page is reloaded or closed
      // mid-request; browsers only allow it for bodies under 64 KB.
      const keepalive = JSON.stringify(body).length < 60_000;
      request("/chat/history", { method: "POST", token, body, keepalive }).catch(() => {});
    }, streaming ? 1500 : 0);
    return () => clearTimeout(timer);
  }, [sessions, activeId, token, historyReady, streaming]);

  // ── Mutation helpers ────────────────────────────────────────────────────
  const updateSession = useCallback((chatId, fn) => {
    setSessions((all) => all.map((s) => (s.id === chatId ? { ...fn(s), updatedAt: Date.now() } : s)));
  }, []);

  const patchMessage = useCallback((chatId, messageId, fields) => {
    setSessions((all) =>
      all.map((s) =>
        s.id !== chatId
          ? s
          : { ...s, messages: s.messages.map((m) => (m.id === messageId ? { ...m, ...(typeof fields === "function" ? fields(m) : fields) } : m)) }
      )
    );
  }, []);

  const setChatBusy = (chatId, value) =>
    setBusy((b) => {
      const next = { ...b };
      if (value) next[chatId] = true;
      else delete next[chatId];
      return next;
    });

  // ── Send ────────────────────────────────────────────────────────────────
  const send = useCallback(
    async (rawText, { deepSearch = false, resendOf = null, fresh = false } = {}) => {
      const text = rawText.trim().slice(0, 2000);
      const state = live.current;
      if (!text) return;

      // `fresh` starts a new conversation even if one is open.
      let chatId = fresh ? null : state.activeId;
      let existing = state.sessions.find((s) => s.id === chatId);
      if (!existing) {
        chatId = Date.now();
        existing = { id: chatId, sid: newSessionId(), title: text.slice(0, 80), messages: [], updatedAt: chatId };
        setSessions((all) => [existing, ...all]);
        setActiveId(chatId);
      }
      if (state.busy[chatId]) return;

      // A retry drops the failed exchange and asks again from that point.
      const cut = resendOf ? existing.messages.findIndex((m) => m.id === resendOf) : -1;
      const earlier = cut >= 0 ? existing.messages.slice(0, cut) : existing.messages;

      const now = Date.now();
      const userMsg = { id: `u${now}`, role: "user", text, at: now };
      const botId = `b${now}`;

      if (state.guestLimitReached) {
        updateSession(chatId, (s) => ({ ...s, messages: [...earlier, userMsg, { id: botId, role: "bot", text: "", at: now, limit: true }] }));
        return;
      }

      const history = conversationHistory(earlier);
      updateSession(chatId, (s) => ({
        ...s,
        title: s.title || text.slice(0, 80),
        messages: [...earlier, userMsg, { id: botId, role: "bot", text: "", at: now, streaming: true, stage: "searching", drafts: [] }],
      }));
      setChatBusy(chatId, true);

      const controller = new AbortController();
      controllers.current[chatId] = controller;
      let written = "";
      let finished = false;

      try {
        const response = await openChatStream(
          {
            message: text,
            session_id: existing.sid,
            deep_search: deepSearch && !state.isGuest,
            preferred_language: state.language,
            conversation_history: history,
          },
          { token: state.token, signal: controller.signal }
        );

        await readEventStream(response, (type, raw) => {
          let data;
          try {
            data = JSON.parse(raw);
          } catch {
            return false;
          }

          switch (type) {
            case "queued":
              patchMessage(chatId, botId, { stage: "queued" });
              break;
            case "route":
              patchMessage(chatId, botId, { stage: "searching" });
              break;
            case "deep_search_step":
              patchMessage(chatId, botId, { stage: "deep", stageDetail: String(data.next_query || "").slice(0, 160) });
              break;
            case "token":
              written += data.token || "";
              patchMessage(chatId, botId, { text: written, stage: "writing" });
              break;
            case "writing":
              patchMessage(chatId, botId, { stage: "writing" });
              break;
            case "translating":
              patchMessage(chatId, botId, { stage: "translating" });
              break;
            case "verifying":
              patchMessage(chatId, botId, { stage: "checking" });
              break;
            case "retry":
              patchMessage(chatId, botId, { stage: "retrying" });
              break;
            case "final_answer":
              patchMessage(chatId, botId, (m) => ({
                text: data.answer || m.text,
                drafts: data.replaced_draft ? [data.replaced_draft] : m.drafts,
                stage: "checking",
              }));
              break;
            case "done":
              finished = true;
              patchMessage(chatId, botId, (m) => ({
                text: data.answer || m.text,
                streaming: false,
                stage: null,
                meta: {
                  confidence: typeof data.confidence_score === "number" ? data.confidence_score : null,
                  citations: Array.isArray(data.citations) ? data.citations.slice(0, 20) : [],
                  retries: data.retry_count || 0,
                  cached: !!data.cache_hit,
                  deep: !!data.deep_search,
                },
              }));
              if (live.current.isGuest) recordGuestAnswer();
              return true;
            case "error":
              finished = true;
              patchMessage(chatId, botId, {
                streaming: false,
                stage: null,
                error: /busy/i.test(data.error || "") ? t("errors.modelBusy") : t("errors.answerFailed"),
              });
              return true;
            default:
              break;
          }
          return false;
        });

        if (!finished) patchMessage(chatId, botId, { streaming: false, stage: null, error: t("errors.incomplete") });
      } catch (err) {
        if (err.name === "AbortError") {
          patchMessage(chatId, botId, { streaming: false, stage: null, stopped: true });
        } else {
          patchMessage(chatId, botId, { streaming: false, stage: null, error: describeError(err, t) });
        }
      } finally {
        delete controllers.current[chatId];
        setChatBusy(chatId, false);
      }
    },
    [patchMessage, updateSession, recordGuestAnswer, t]
  );

  const retry = useCallback(
    (botMessageId) => {
      const session = live.current.sessions.find((s) => s.id === live.current.activeId);
      if (!session) return;
      const index = session.messages.findIndex((m) => m.id === botMessageId);
      const question = [...session.messages.slice(0, index)].reverse().find((m) => m.role === "user");
      if (question) send(question.text, { resendOf: question.id });
    },
    [send]
  );

  const stop = useCallback(() => controllers.current[live.current.activeId]?.abort(), []);

  const rate = useCallback(
    (messageId, up) => {
      const chatId = live.current.activeId;
      patchMessage(chatId, messageId, { feedback: up ? "up" : "down" });
      const sid = live.current.sessions.find((s) => s.id === chatId)?.sid || "unknown";
      request("/feedback", {
        method: "POST",
        body: { session_id: sid, message_id: messageId, thumbs_up: up },
      }).catch(() => {});
    },
    [patchMessage]
  );

  const deleteChat = useCallback((chatId) => {
    controllers.current[chatId]?.abort();
    setSessions((all) => all.filter((s) => s.id !== chatId));
    setActiveId((id) => (id === chatId ? null : id));
  }, []);

  const clearAll = useCallback(async () => {
    Object.values(controllers.current).forEach((c) => c.abort());
    setSessions([]);
    setActiveId(null);
    if (live.current.token) {
      await request("/chat/history", { method: "DELETE", token: live.current.token });
    }
  }, []);

  const exportAll = useCallback(() => {
    const data = live.current.sessions.map((s) => ({
      title: s.title,
      messages: s.messages
        .filter((m) => m.text)
        .map((m) => ({
          role: m.role === "bot" ? "vidhi" : "you",
          at: m.at ? new Date(m.at).toISOString() : null,
          text: m.text,
          sources: m.meta?.citations?.map((c) => [c.document_title, c.section].filter(Boolean).join(" · ")) || undefined,
        })),
    }));
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: `vidhi-chats-${new Date().toLocaleDateString("en-CA")}.json` });
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const activeChat = sessions.find((s) => s.id === activeId) || null;

  const value = useMemo(
    () => ({
      sessions,
      activeChat,
      activeId,
      isBusy: !!busy[activeId],
      busyIds: busy,
      historyReady,
      send,
      stop,
      retry,
      rate,
      newChat: () => setActiveId(null),
      selectChat: setActiveId,
      deleteChat,
      clearAll,
      exportAll,
    }),
    [sessions, activeChat, activeId, busy, historyReady, send, stop, retry, rate, deleteChat, clearAll, exportAll]
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used inside ChatProvider");
  return ctx;
}
