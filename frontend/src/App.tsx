import { useEffect, useState } from "react";
import PortalApp from "./pages/portal/PortalApp";
import SupportConsole from "./pages/SupportConsole";

function isSupportRoute(hash: string) {
  return hash.replace(/^#/, "").startsWith("/support");
}

export default function App() {
  const [supportMode, setSupportMode] = useState(isSupportRoute(window.location.hash));

  useEffect(() => {
    const handleChange = () => setSupportMode(isSupportRoute(window.location.hash));
    window.addEventListener("hashchange", handleChange);
    return () => window.removeEventListener("hashchange", handleChange);
  }, []);

  if (supportMode) {
    return <SupportConsole />;
  }

  return <PortalApp />;
}
