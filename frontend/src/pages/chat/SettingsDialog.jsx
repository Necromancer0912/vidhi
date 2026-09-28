import { useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "../../components/Icon";
import { Dialog } from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import { useChat } from "../../context/ChatContext";
import { usePrefs } from "../../context/PrefsContext";
import { useToast } from "../../context/ToastContext";
import { describeError, request } from "../../lib/api";
import { LANGUAGES } from "../../lib/languages";

function Section({ title, children }) {
  return (
    <section className="border-b border-line py-5 first:pt-0 last:border-0 last:pb-0">
      <h3 className="mb-3 text-sm font-medium text-muted">{title}</h3>
      {children}
    </section>
  );
}

export default function SettingsDialog({ open, onClose }) {
  const { t } = useTranslation();
  const toast = useToast();
  const { user, token, isGuest, signOut } = useAuth();
  const { theme, setTheme, language, setLanguage } = usePrefs();
  const { sessions, exportAll, clearAll } = useChat();
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const close = () => {
    setConfirmClear(false);
    setConfirmDelete(false);
    onClose();
  };

  const deleteAccount = async () => {
    try {
      await request("/auth/account", { method: "DELETE", token });
      signOut();
      close();
      toast(t("settings.accountDeleted"));
    } catch (err) {
      toast(describeError(err, t), "error");
    }
  };

  const clear = async () => {
    try {
      await clearAll();
      toast(t("settings.cleared"));
    } catch (err) {
      toast(describeError(err, t), "error");
    }
    setConfirmClear(false);
  };

  return (
    <Dialog open={open} onClose={close} title={t("settings.title")}>
      <Section title={t("settings.account")}>
        {isGuest ? (
          <p className="text-[15px] leading-relaxed text-ink-2">{t("settings.guestAccount")}</p>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate font-medium">{user.name}</p>
              <p className="truncate text-sm text-muted">{user.email}</p>
            </div>
            <button
              type="button"
              onClick={() => {
                signOut();
                close();
              }}
              className="flex h-10 shrink-0 items-center gap-2 rounded-full border border-line px-4 text-sm transition hover:bg-stone"
            >
              <Icon name="logOut" size={16} />
              {t("settings.signOut")}
            </button>
          </div>
        )}
        {!isGuest &&
          (confirmDelete ? (
            <div className="mt-4 rounded-[14px] bg-danger/10 p-4">
              <p className="text-sm text-ink">{t("settings.deleteAccountWarning")}</p>
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={deleteAccount} className="h-9 rounded-full bg-danger px-4 text-sm font-medium text-white dark:text-[#11130f]">
                  {t("settings.deleteAccount")}
                </button>
                <button type="button" onClick={() => setConfirmDelete(false)} className="h-9 rounded-full px-3 text-sm text-ink-2 hover:text-ink">
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirmDelete(true)} className="mt-3 text-sm text-muted underline underline-offset-4 hover:text-danger">
              {t("settings.deleteAccount")}
            </button>
          ))}
      </Section>

      <Section title={t("settings.language")}>
        <p className="mb-3 text-sm text-ink-2">{t("settings.languageHelp")}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              type="button"
              lang={lang.code}
              aria-pressed={language === lang.code}
              onClick={() => setLanguage(lang.code)}
              className={`min-h-11 rounded-[12px] px-3 py-2 text-sm transition ${
                language === lang.code ? "bg-invert text-on-invert" : "bg-stone text-ink hover:bg-line"
              }`}
            >
              {lang.name}
            </button>
          ))}
        </div>
      </Section>

      <Section title={t("settings.appearance")}>
        <div className="grid grid-cols-2 gap-2">
          {["light", "dark"].map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={theme === mode}
              onClick={() => setTheme(mode)}
              className={`flex h-11 items-center justify-center gap-2 rounded-[12px] text-sm transition ${
                theme === mode ? "bg-invert text-on-invert" : "bg-stone text-ink hover:bg-line"
              }`}
            >
              <Icon name={mode === "light" ? "sun" : "moon"} size={16} />
              {t(`settings.${mode}`)}
            </button>
          ))}
        </div>
      </Section>

      <Section title={t("settings.data")}>
        <p className="mb-4 text-sm leading-relaxed text-ink-2">{isGuest ? t("settings.guestData") : t("settings.accountData")}</p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={exportAll}
            disabled={!sessions.length}
            className="flex h-10 items-center gap-2 rounded-full border border-line px-4 text-sm transition hover:bg-stone disabled:opacity-50"
          >
            <Icon name="download" size={16} />
            {t("settings.export")}
          </button>
          {confirmClear ? (
            <span className="flex items-center gap-2">
              <button type="button" onClick={clear} className="h-10 rounded-full bg-danger px-4 text-sm font-medium text-white dark:text-[#11130f]">
                {t("settings.confirmClear")}
              </button>
              <button type="button" onClick={() => setConfirmClear(false)} className="h-10 rounded-full px-3 text-sm text-ink-2 hover:text-ink">
                {t("common.cancel")}
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmClear(true)}
              disabled={!sessions.length}
              className="flex h-10 items-center gap-2 rounded-full border border-line px-4 text-sm text-danger transition hover:bg-danger/10 disabled:opacity-50"
            >
              <Icon name="trash" size={16} />
              {t("settings.clear")}
            </button>
          )}
        </div>
      </Section>
    </Dialog>
  );
}
