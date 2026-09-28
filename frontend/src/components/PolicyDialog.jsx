import { createContext, useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog } from "./ui";

// Number of numbered sections each policy has in the translation file.
const SECTIONS = { terms: 5, privacy: 6, disclaimer: 4 };

const PolicyContext = createContext(() => {});

export function PolicyProvider({ children }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState(null);

  return (
    <PolicyContext.Provider value={setKind}>
      {children}
      <Dialog open={!!kind} onClose={() => setKind(null)} title={kind ? t(`policies.${kind}.title`) : ""} wide>
        {kind && (
          <div className="space-y-5 text-[15px] leading-relaxed text-ink-2">
            <p className="text-sm text-muted">{t(`policies.${kind}.intro`)}</p>
            {Array.from({ length: SECTIONS[kind] }, (_, i) => (
              <section key={i}>
                <h3 className="mb-1.5 font-medium text-ink">{t(`policies.${kind}.s${i + 1}Title`)}</h3>
                <p>{t(`policies.${kind}.s${i + 1}Body`)}</p>
              </section>
            ))}
          </div>
        )}
      </Dialog>
    </PolicyContext.Provider>
  );
}

// openPolicy("terms" | "privacy" | "disclaimer")
export const useOpenPolicy = () => useContext(PolicyContext);
