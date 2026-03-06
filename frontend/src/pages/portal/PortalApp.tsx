import { useEffect, useState } from "react";

import AccessoriesStorePage from "./AccessoriesStorePage";
import AuthLoginPage from "./AuthLoginPage";
import AuthRegisterPage from "./AuthRegisterPage";
import HomeDashboard from "./HomeDashboard";
import OrderDetailPage from "./OrderDetailPage";
import OrderFlowPage from "./OrderFlowPage";
import OrderListPage from "./OrderListPage";
import PortalShell from "./layout/PortalShell";
import ProfileCenterPage from "./ProfileCenterPage";
import SupportChatPage from "./SupportChatPage";

type RouteState = {
  path: string;
  params: Record<string, string>;
  query: Record<string, string>;
};
type PortalTheme = "light" | "eye" | "dark";

const DASHBOARD_PATH = "/portal/dashboard";
const PORTAL_THEME_KEY = "portal_theme";

function normalizePath(rawPath: string) {
  if (rawPath === "/portal" || rawPath === "/portal/" || rawPath === "/portal/home") {
    return DASHBOARD_PATH;
  }
  return rawPath;
}

function parseRoute(rawHash: string): RouteState {
  const hash = rawHash.replace(/^#/, "");
  const raw = hash.startsWith("/") ? hash : `/${hash || "portal/dashboard"}`;
  const [rawPath, rawQuery = ""] = raw.split("?");
  const path = normalizePath(rawPath);

  const params: Record<string, string> = {};
  const query: Record<string, string> = {};
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "portal" && parts[1] === "orders" && parts[2]) {
    params.orderId = parts[2];
  }
  const search = new URLSearchParams(rawQuery);
  search.forEach((value, key) => {
    query[key] = value;
  });
  return { path, params, query };
}

function useHashRoute() {
  const [route, setRoute] = useState<RouteState>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const handleChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", handleChange);
    if (!window.location.hash) {
      window.location.hash = "#/portal/dashboard";
    }
    return () => window.removeEventListener("hashchange", handleChange);
  }, []);

  return route;
}

export default function PortalApp() {
  const route = useHashRoute();
  const [theme, setTheme] = useState<PortalTheme>(() => {
    const saved = (localStorage.getItem(PORTAL_THEME_KEY) || "").trim() as PortalTheme;
    return saved === "eye" || saved === "dark" ? saved : "light";
  });
  const isOrderDetail = route.path.startsWith("/portal/orders/");
  const knownPaths = new Set([
    DASHBOARD_PATH,
    "/portal/orders",
    "/portal/order/new",
    "/portal/store",
    "/portal/profile",
    "/portal/chat",
    "/portal/login",
    "/portal/register"
  ]);
  const authPaths = new Set(["/portal/login", "/portal/register"]);
  const resolvedPath = knownPaths.has(route.path) || isOrderDetail ? route.path : DASHBOARD_PATH;
  const token = localStorage.getItem("portal_token");

  useEffect(() => {
    if (!token && !authPaths.has(resolvedPath)) {
      window.location.hash = "#/portal/login";
      return;
    }
    if (token && authPaths.has(resolvedPath)) {
      window.location.hash = "#/portal/dashboard";
    }
  }, [token, resolvedPath]);

  useEffect(() => {
    document.documentElement.setAttribute("data-portal-theme", theme);
    localStorage.setItem(PORTAL_THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const onThemeChange = (event: Event) => {
      const custom = event as CustomEvent<{ theme?: PortalTheme }>;
      const nextTheme = custom.detail?.theme;
      if (nextTheme === "light" || nextTheme === "eye" || nextTheme === "dark") {
        setTheme(nextTheme);
      }
    };
    window.addEventListener("portal:theme-change", onThemeChange as EventListener);
    return () => window.removeEventListener("portal:theme-change", onThemeChange as EventListener);
  }, []);

  if (!token && !authPaths.has(resolvedPath)) {
    return (
      <div className="portal-app portal-shell auth-shell">
        <AuthLoginPage />
      </div>
    );
  }

  if (authPaths.has(resolvedPath)) {
    return (
      <div className="portal-app portal-shell auth-shell">
        {resolvedPath === "/portal/login" ? <AuthLoginPage /> : <AuthRegisterPage />}
      </div>
    );
  }

  const activePath = resolvedPath.startsWith("/portal/orders/") ? "/portal/orders" : resolvedPath;

  let content = <HomeDashboard />;
  if (resolvedPath === "/portal/orders") {
    content = (
      <OrderListPage
        initialStatus={route.query.status}
        initialKeyword={route.query.keyword}
      />
    );
  } else if (resolvedPath.startsWith("/portal/orders/")) {
    content = <OrderDetailPage orderId={route.params.orderId} />;
  } else if (resolvedPath === "/portal/order/new") {
    content = <OrderFlowPage initialServiceCode={route.query.service} />;
  } else if (resolvedPath === "/portal/store") {
    content = <AccessoriesStorePage />;
  } else if (resolvedPath === "/portal/profile") {
    content = <ProfileCenterPage />;
  } else if (resolvedPath === "/portal/chat") {
    content = <SupportChatPage />;
  }

  return (
    <PortalShell activePath={activePath} theme={theme} onThemeChange={setTheme}>
      {content}
    </PortalShell>
  );
}
