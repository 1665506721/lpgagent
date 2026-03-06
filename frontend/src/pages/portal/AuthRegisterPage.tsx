import { useState } from "react";

import { registerPortal, requestSmsCode } from "../../lib/portalApi";

function isValidPortalPhone(phone: string) {
  const normalized = (phone || "").trim();
  if (normalized === "123") return true;
  return /^1[3-9]\d{9}$/.test(normalized);
}

export default function AuthRegisterPage() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [company, setCompany] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  const [smsHint, setSmsHint] = useState("");
  const [smsSending, setSmsSending] = useState(false);
  const [registering, setRegistering] = useState(false);

  const handleRegister = async () => {
    setError("");
    if (!phone.trim() || !code.trim() || !password.trim() || !confirm.trim()) {
      setError("请完善注册信息");
      return;
    }
    if (!isValidPortalPhone(phone)) {
      setError("手机号格式不正确（仅支持中国大陆手机号，测试号除外）");
      return;
    }
    if (password !== confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    if (!agreed) {
      setError("请先同意服务协议与隐私政策");
      return;
    }

    setRegistering(true);
    try {
      const result = await registerPortal({
        phone: phone.trim(),
        password: password.trim(),
        sms_code: code.trim(),
        display_name: company.trim() || phone.trim()
      });
      localStorage.setItem("portal_token", result.token);
      localStorage.setItem("portal_profile_phone", result.profile.phone || phone.trim());
      localStorage.setItem("portal_profile_id", String(result.profile.id || ""));
      window.location.hash = "#/portal/dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败，请稍后再试");
    } finally {
      setRegistering(false);
    }
  };

  const handleSendCode = async () => {
    setError("");
    setSmsHint("");

    if (!phone.trim()) {
      setError("请先填写手机号");
      return;
    }
    if (!isValidPortalPhone(phone)) {
      setError("手机号格式不正确（仅支持中国大陆手机号，测试号除外）");
      return;
    }

    setSmsSending(true);
    try {
      const result = await requestSmsCode(phone.trim());
      setSmsHint(`验证码已发送（测试验证码：${result.code}）`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送验证码失败");
    } finally {
      setSmsSending(false);
    }
  };

  return (
    <div className="portal-auth">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="portal-logo">L</div>
          <div>
            <div className="portal-brand-title">LPG 服务平台</div>
            <div className="portal-brand-sub">企业用户注册</div>
          </div>
        </div>

        <div className="auth-title">创建企业账号</div>
        <div className="auth-subtitle">完成手机号验证后即可使用平台服务</div>

        <div className="auth-form">
          <label>
            <span>手机号</span>
            <input
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="请输入 11 位手机号"
            />
          </label>

          <label>
            <span>短信验证码</span>
            <div className="auth-inline">
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="请输入验证码"
              />
              <button className="portal-secondary" type="button" onClick={handleSendCode} disabled={smsSending}>
                {smsSending ? "发送中..." : "获取验证码"}
              </button>
            </div>
          </label>

          <label>
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="设置登录密码"
            />
          </label>

          <label>
            <span>确认密码</span>
            <input
              type="password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              placeholder="再次输入密码"
            />
          </label>

          <label>
            <span>企业名称（可选）</span>
            <input
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              placeholder="请输入企业/单位名称"
            />
          </label>

          <label className="auth-checkbox">
            <input type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
            <span>
              我已阅读并同意 <a href="#/portal/register">服务协议</a> 与 <a href="#/portal/register">隐私政策</a>
            </span>
          </label>

          {smsHint ? <div className="auth-hint">{smsHint}</div> : null}
          {error ? <div className="auth-error">{error}</div> : null}

          <button className="portal-cta full" type="button" onClick={handleRegister} disabled={registering}>
            {registering ? "注册中..." : "注册并登录"}
          </button>
        </div>

        <div className="auth-footer">
          已有账号？<a href="#/portal/login">去登录</a>
          <span className="auth-divider">|</span>
          <a href="#/portal/dashboard">返回首页</a>
        </div>
      </div>
    </div>
  );
}
