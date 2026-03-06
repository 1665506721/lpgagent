import type { ReactNode } from "react";

import PortalTopNav from "./PortalTopNav";

type PortalShellProps = {
  activePath: string;
  theme: "light" | "eye" | "dark";
  onThemeChange: (theme: "light" | "eye" | "dark") => void;
  children: ReactNode;
};

export default function PortalShell({ activePath, theme, onThemeChange, children }: PortalShellProps) {
  return (
    <div className="portal-app portal-shell">
      <PortalTopNav activePath={activePath} theme={theme} onThemeChange={onThemeChange} />
      <main className="portal-content wide">{children}</main>
    </div>
  );
}
