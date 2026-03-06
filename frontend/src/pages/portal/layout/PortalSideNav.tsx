import { NAV_LINKS } from "../portalData";

type PortalSideNavProps = {
  activePath: string;
};

export default function PortalSideNav({ activePath }: PortalSideNavProps) {
  return (
    <aside className="portal-side-nav">
      <div className="portal-brand vertical">
        <div className="portal-logo">L</div>
        <div>
          <div className="portal-brand-title">LPG 服务平台</div>
          <div className="portal-brand-sub">运营概览</div>
        </div>
      </div>
      <div className="portal-side-links">
        {NAV_LINKS.map((link) => {
          const isActive =
            activePath === link.path || activePath.startsWith(`${link.path}/`);
          return (
            <a
              key={link.path}
              href={`#${link.path}`}
              className={isActive ? "portal-link active" : "portal-link"}
            >
              <span className="portal-link-dot" />
              {link.label}
            </a>
          );
        })}
      </div>
      <div className="portal-side-footer">
        <div className="portal-user-card">
          <div className="portal-user-avatar">张</div>
          <div>
            <div className="portal-user-name">张建国</div>
            <div className="portal-user-meta">高级会员</div>
          </div>
        </div>
        <button className="portal-ghost" type="button">
          ⚙ 设置
        </button>
      </div>
    </aside>
  );
}
