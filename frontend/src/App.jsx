import { lazy, Suspense, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { PolicyProvider } from "./components/PolicyDialog";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ChatProvider } from "./context/ChatContext";
import { PrefsProvider } from "./context/PrefsContext";
import { ToastProvider, useToast } from "./context/ToastContext";
import { RouterProvider, useRouter } from "./lib/router";
import Landing from "./pages/Landing";

const ChatPage = lazy(() => import("./pages/chat/ChatPage"));
const Library = lazy(() => import("./pages/Library"));
const SignIn = lazy(() => import("./pages/SignIn"));

const ROUTES = {
  "/": { page: Landing, title: "titles.home" },
  "/chat": { page: ChatPage, title: "titles.chat" },
  "/library": { page: Library, title: "titles.library" },
  "/signin": { page: SignIn, title: "titles.signin" },
};

function Blank() {
  return <div className="min-h-screen bg-page" />;
}

function Routes() {
  const { t } = useTranslation();
  const { path, navigate } = useRouter();
  const { sessionExpired } = useAuth();
  const toast = useToast();
  const route = ROUTES[path];

  useEffect(() => {
    if (!route) navigate("/", { replace: true });
  }, [route, navigate]);

  useEffect(() => {
    if (route) document.title = t(route.title);
  }, [route, t]);

  useEffect(() => {
    if (sessionExpired) toast(t("errors.sessionExpired"), "error");
  }, [sessionExpired, toast, t]);

  const Page = (route || ROUTES["/"]).page;
  return (
    <Suspense fallback={<Blank />}>
      <Page />
    </Suspense>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Blank />}>
      <RouterProvider>
        <PrefsProvider>
          <ToastProvider>
            <AuthProvider>
              <ChatProvider>
                <PolicyProvider>
                  <Routes />
                </PolicyProvider>
              </ChatProvider>
            </AuthProvider>
          </ToastProvider>
        </PrefsProvider>
      </RouterProvider>
    </Suspense>
  );
}
