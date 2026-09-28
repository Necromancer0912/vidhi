import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../../components/Icon";
import { useAuth } from "../../context/AuthContext";
import { useChat } from "../../context/ChatContext";
import { usePrefs } from "../../context/PrefsContext";
import { useFormat } from "../../lib/format";
import { languageInfo } from "../../lib/languages";
import { Link } from "../../lib/router";

const MAX_CHARS = 2000;
const SpeechRecognition = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

export default function Composer() {
  const { t } = useTranslation();
  const { isGuest } = useAuth();
  const { language } = usePrefs();
  const { send, stop, isBusy, activeId } = useChat();
  const { num } = useFormat();

  const [text, setText] = useState("");
  const [deep, setDeep] = useState(false);
  const [deepTip, setDeepTip] = useState(false);
  const [listening, setListening] = useState(false);
  const inputRef = useRef(null);
  const recognition = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, [activeId]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  useEffect(() => () => recognition.current?.abort(), []);

  const submit = () => {
    if (!text.trim() || isBusy) return;
    send(text, { deepSearch: deep && !isGuest });
    setText("");
  };

  const toggleVoice = () => {
    if (listening) {
      recognition.current?.stop();
      return;
    }
    const r = new SpeechRecognition();
    r.lang = languageInfo(language).speech;
    r.interimResults = false;
    r.onresult = (e) => {
      const heard = e.results[0][0].transcript;
      setText((prev) => `${prev}${prev ? " " : ""}${heard}`.slice(0, MAX_CHARS));
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    recognition.current = r;
    setListening(true);
    r.start();
  };

  return (
    <div>
      {deepTip && (
        <p className="animate-fade mb-2 flex items-center justify-between gap-3 rounded-[14px] bg-stone px-4 py-2.5 text-sm text-ink-2">
          <span>{t("chat.deepLocked")}</span>
          <Link to="/signin" className="shrink-0 font-medium text-ink underline underline-offset-4">
            {t("nav.signIn")}
          </Link>
        </p>
      )}

      <div className="rounded-[24px] border border-line bg-sheet p-2 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.18)] transition focus-within:border-ink/30">
        <label htmlFor="question" className="sr-only">
          {t("chat.placeholder")}
        </label>
        <textarea
          id="question"
          ref={inputRef}
          rows={1}
          value={text}
          maxLength={MAX_CHARS}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // isComposing: don't send while an Indic IME is mid-character.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={t("chat.placeholder")}
          className="block max-h-[200px] w-full resize-none bg-transparent px-3 pb-2 pt-2.5 text-[15px] leading-relaxed text-ink outline-none placeholder:text-muted"
        />

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-pressed={deep && !isGuest}
            onClick={() => (isGuest ? setDeepTip((v) => !v) : setDeep((v) => !v))}
            title={t("chat.deepExplain")}
            className={`flex h-9 items-center gap-1.5 rounded-full px-3 text-sm transition ${
              deep && !isGuest ? "bg-lime text-on-lime" : "text-ink-2 hover:bg-stone hover:text-ink"
            }`}
          >
            <Icon name={isGuest ? "lock" : "sparkle"} size={16} />
            {t("chat.deepSearch")}
          </button>

          <span className="ml-auto flex items-center gap-1.5">
            {text.length > MAX_CHARS - 300 && (
              <span className="text-xs text-muted" aria-live="polite">
                {t("chat.charCount", { n: num(text.length), max: num(MAX_CHARS) })}
              </span>
            )}
            {SpeechRecognition && (
              <button
                type="button"
                onClick={toggleVoice}
                aria-pressed={listening}
                aria-label={listening ? t("chat.stopListening") : t("chat.speak")}
                title={listening ? t("chat.stopListening") : t("chat.speak")}
                className={`grid h-9 w-9 place-items-center rounded-full transition ${
                  listening ? "animate-pulse bg-danger/15 text-danger" : "text-ink-2 hover:bg-stone hover:text-ink"
                }`}
              >
                <Icon name="mic" size={17} />
              </button>
            )}
            {isBusy ? (
              <button type="button" onClick={stop} aria-label={t("chat.stop")} title={t("chat.stop")} className="grid h-9 w-9 place-items-center rounded-full bg-invert text-on-invert">
                <Icon name="stop" size={15} />
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={!text.trim()}
                aria-label={t("chat.send")}
                title={t("chat.send")}
                className="grid h-9 w-9 place-items-center rounded-full bg-invert text-on-invert transition disabled:bg-stone disabled:text-muted"
              >
                <Icon name="arrowUp" size={17} strokeWidth={2.2} />
              </button>
            )}
          </span>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-muted">{t("chat.disclaimer")}</p>
    </div>
  );
}
