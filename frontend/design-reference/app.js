/* global document, fetch, window */

const config = Object.assign(
  {
    apiBaseUrl:
      document.querySelector('meta[name="linguasphere-api-base-url"]')?.content ??
      "",
    successPath:
      document.querySelector('meta[name="linguasphere-login-success-path"]')
        ?.content ?? "/",
  },
  window.LINGUASPHERE_LOGIN_CONFIG || {},
);

const form = document.querySelector("#login-form");
const loginNameInput = document.querySelector("#login-name");
const passwordInput = document.querySelector("#password");
const rememberInput = document.querySelector("#remember-login-name");
const togglePassword = document.querySelector("#toggle-password");
const submitButton = document.querySelector("#submit-button");
const message = document.querySelector("#form-message");
const rememberedKey = "linguasphere.rememberedLoginName";

function readRememberedLoginName() {
  try {
    return window.localStorage.getItem(rememberedKey) || "";
  } catch {
    return "";
  }
}

function updateRememberedLoginName(loginName) {
  try {
    if (rememberInput.checked) {
      window.localStorage.setItem(rememberedKey, loginName);
    } else {
      window.localStorage.removeItem(rememberedKey);
    }
  } catch {
    // Storage can be disabled without blocking authentication.
  }
}

function setMessage(text = "", tone = "") {
  message.textContent = text;
  message.className = "form-message";
  if (tone) message.classList.add(`form-message--${tone}`);
}

export async function requestLogin(loginName, password) {
  const response = await fetch(`${config.apiBaseUrl}/api/v1/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loginName, password }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      payload?.error?.message || "登录请求未完成，请稍后重试",
    );
  }
  return payload;
}

const rememberedLoginName = readRememberedLoginName();
if (rememberedLoginName) {
  loginNameInput.value = rememberedLoginName;
  rememberInput.checked = true;
}

togglePassword.addEventListener("click", () => {
  const shouldShow = passwordInput.type === "password";
  passwordInput.type = shouldShow ? "text" : "password";
  togglePassword.setAttribute("aria-pressed", String(shouldShow));
  togglePassword.setAttribute("aria-label", shouldShow ? "隐藏密码" : "显示密码");
  togglePassword.querySelector("span").textContent = shouldShow ? "隐藏" : "显示";
  passwordInput.focus({ preventScroll: true });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage();

  const loginName = loginNameInput.value.trim();
  const password = passwordInput.value;
  if (!loginName || !password) {
    setMessage("请完整输入账号和密码。", "error");
    (!loginName ? loginNameInput : passwordInput).focus();
    return;
  }

  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "正在验证…";

  try {
    await requestLogin(loginName, password);
    updateRememberedLoginName(loginName);
    window.location.assign(config.successPath);
  } catch (error) {
    setMessage(error instanceof Error ? error.message : "登录服务暂时不可用", "error");
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "登录工作台";
  }
});
