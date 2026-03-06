import { SERVICE_CARDS } from "./portalData";

const METRICS = [
  { label: "本月用气量", value: "45.8 kg", sub: "较上月下降 12%", tone: "primary" },
  { label: "安全评分", value: "优秀 98", sub: "下次安检：2026-03-20", tone: "default" },
  { label: "待处理订单", value: "2 单", sub: "1 单待支付，1 单待服务", tone: "default" },
  { label: "积分余额", value: "1,240", sub: "可用于配件抵扣", tone: "default" }
] as const;

export default function HomeDashboard() {
  return (
    <div className="portal-page dashboard-page">
      <section className="dashboard-hero portal-card">
        <div>
          <div className="portal-welcome">你好，欢迎回到 LPG 企业工作台</div>
          <div className="portal-welcome-sub">一站式完成下单、订单跟踪、配件采购和在线客服。</div>
        </div>
        <div className="dashboard-hero-actions">
          <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/orders")}>
            查看全部订单
          </button>
          <button className="portal-cta" type="button" onClick={() => (window.location.hash = "#/portal/order/new")}>
            立即下单
          </button>
        </div>
      </section>

      <section className="portal-section">
        <div className="portal-section-header">
          <h2>常用服务</h2>
          <a className="portal-link small" href="#/portal/order/new">
            进入服务下单
          </a>
        </div>
        <div className="portal-grid six dashboard-service-grid">
          {SERVICE_CARDS.map((card) => (
            <button
              key={card.id}
              type="button"
              className="portal-card service-card dashboard-service-card"
              onClick={() => {
                if (card.code === "ACCESSORIES") {
                  window.location.hash = "#/portal/store";
                  return;
                }
                window.location.hash = `#/portal/order/new?service=${card.code}`;
              }}
            >
              <div className="service-icon">{card.icon}</div>
              <div className="service-title">{card.title}</div>
              <div className="service-desc">{card.desc}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="portal-section dashboard-main-grid">
        <div className="portal-card order-progress dashboard-focus-card">
          <div className="portal-section-header compact">
            <h2>进行中订单</h2>
            <span className="portal-pill active">1 个进行中</span>
          </div>
          <div className="order-progress-main">
            <div>
              <div className="order-badge">配送中</div>
              <div className="order-title">液化气配送（15kg x 2）预计 30 分钟内送达</div>
              <div className="order-meta">订单号：LPG2026020910261124</div>
            </div>
            <div className="order-driver">
              <div className="driver-avatar">李</div>
              <div>
                <div className="driver-name">配送员 李师傅</div>
                <div className="driver-meta">评分 4.9</div>
              </div>
            </div>
          </div>
          <div className="order-timeline">
            <div className="timeline-step active">
              <span />
              下单成功
            </div>
            <div className="timeline-step active">
              <span />
              备货中
            </div>
            <div className="timeline-step active">
              <span />
              配送中
            </div>
            <div className="timeline-step">
              <span />
              已送达
            </div>
          </div>
          <div className="order-actions">
            <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/orders")}>
              查看订单列表
            </button>
            <button className="portal-cta" type="button" onClick={() => (window.location.hash = "#/portal/chat")}>
              联系客服
            </button>
          </div>
        </div>

        <div className="dashboard-side-column">
          <div className="portal-card dashboard-side-card safety-card">
            <div>
              <div className="portal-card-title">安全用气提醒</div>
              <div className="portal-note">请定期检查管道与阀门，长期未使用前先通风后点火。</div>
            </div>
            <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/chat")}>查看详情</button>
          </div>
        </div>
      </section>

      <section className="stats-grid dashboard-stats-grid">
        {METRICS.map((metric) => (
          <div key={metric.label} className={`portal-card stat-card ${metric.tone === "primary" ? "highlight" : ""}`}>
            <div className="stat-title">{metric.label}</div>
            <div className="stat-value">{metric.value}</div>
            <div className="stat-sub">{metric.sub}</div>
          </div>
        ))}
      </section>
    </div>
  );
}
