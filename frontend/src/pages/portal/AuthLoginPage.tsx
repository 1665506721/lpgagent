import { useState } from "react";

import { loginPortal } from "../../lib/portalApi";

export default function AuthLoginPage() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [hint, setHint] = useState("可使用测试账号：手机号 123，密码 123");
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setError("");
    setHint("");
    if (!phone.trim() || !password.trim()) {
      setError("请输入手机号和密码");
      return;
    }

    setLoading(true);
    try {
      const result = await loginPortal(phone.trim(), password.trim());
      localStorage.setItem("portal_token", result.token);
      localStorage.setItem("portal_profile_phone", result.profile.phone || phone.trim());
      localStorage.setItem("portal_profile_id", String(result.profile.id || ""));
      window.location.hash = "#/portal/dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="portal-auth">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="portal-logo">L</div>
          <div>
            <div className="portal-brand-title">LPG 服务平台</div>
            <div className="portal-brand-sub">企业用户登录</div>
          </div>
        </div>

        <div className="auth-title">欢迎回来</div>
        <div className="auth-subtitle">请输入手机号与密码登录账号</div>

        <div className="auth-form">
          <label>
            <span>手机号</span>
            <input
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="请输入手机号（或测试号 123）"
            />
          </label>

          <label>
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入账号密码"
            />
          </label>

          <div className="auth-row">
            <label className="auth-checkbox">
              <input type="checkbox" />
              <span>记住账号</span>
            </label>
            <button
              className="auth-link"
              type="button"
              onClick={() => setHint("MVP 暂不支持在线找回，请联系管理员重置密码。")}
            >
              忘记密码？
            </button>
          </div>

          {hint ? <div className="auth-hint">{hint}</div> : null}
          {error ? <div className="auth-error">{error}</div> : null}

          <button className="portal-cta full" type="button" onClick={handleLogin} disabled={loading}>
            {loading ? "登录中..." : "登录"}
          </button>
        </div>

        <div className="auth-footer">
          还没有账号？<a href="#/portal/register">立即注册</a>
          <span className="auth-divider">|</span>
          <a href="#/portal/dashboard">返回首页</a>
        </div>
      </div>
    </div>
  );
}
