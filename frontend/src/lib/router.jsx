import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// A small History-API router: four routes don't justify a dependency.
const RouterContext = createContext(null);

function current() {
  return { path: window.location.pathname, hash: window.location.hash, state: window.history.state };
}

function scrollToHash(hash) {
  if (!hash) {
    window.scrollTo({ top: 0 });
    return;
  }
  // Wait a frame so the target section has rendered after a route change.
  requestAnimationFrame(() => document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" }));
}

export function RouterProvider({ children }) {
  const [location, setLocation] = useState(current);

  useEffect(() => {
    const onPop = () => setLocation(current());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((to, { state = null, replace = false } = {}) => {
    const url = new URL(to, window.location.origin);
    window.history[replace ? "replaceState" : "pushState"](state, "", url.pathname + url.search + url.hash);
    setLocation(current());
    if (!replace) scrollToHash(url.hash);
  }, []);

  // Clears one-shot navigation state (e.g. a prompt to send) so a refresh or
  // back navigation doesn't replay it.
  const clearState = useCallback(() => {
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    setLocation(current());
  }, []);

  const value = useMemo(() => ({ ...location, navigate, clearState }), [location, navigate, clearState]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function useRouter() {
  return useContext(RouterContext);
}

export function Link({ to, onClick, children, ...rest }) {
  const { navigate } = useRouter();
  return (
    <a
      href={to}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigate(to);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}
