import { createContext, useCallback, useContext, useRef, useState } from "react";

const ToastContext = createContext(() => {});

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);

  const show = useCallback((message, tone = "ok") => {
    clearTimeout(timer.current);
    setToast({ message, tone, key: Date.now() });
    timer.current = setTimeout(() => setToast(null), 3200);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-6 z-[200] flex justify-center px-4">
        {toast && (
          <div
            key={toast.key}
            className="animate-rise flex items-center gap-2.5 rounded-full bg-invert px-4 py-2.5 text-sm text-on-invert shadow-lg"
          >
            <span className={`h-2 w-2 rounded-full ${toast.tone === "error" ? "bg-danger" : "bg-lime"}`} />
            {toast.message}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
