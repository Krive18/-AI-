# 寰语深色霓虹界面升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Vue 3 登录页、用户端和管理端统一升级为与参考图一致的“寰语”深色霓虹视频全球化工作台，同时保留真实 API 与现有业务逻辑。

**Architecture:** 正式应用继续使用 Vue 3、TypeScript、Pinia 和 Vue Router，通过新增设计变量、品牌组件与公共样式完成界面升级。登录流仍由 `useAuthStore().login(loginName, password)` 调用真实后端；另外交付一份不参与 Vite 构建的三文件登录视觉样板。

**Tech Stack:** Vue 3.5、TypeScript 6、Pinia 4、Vue Router 5、Vite 8、Vitest、Vue Test Utils、@lucide/vue、CSS Custom Properties。

**Spec:** `docs/superpowers/specs/2026-09-02-linguasphere-neon-ui-design.md`

## Global Constraints

- 正式前端保留 Vue 3 架构，不转换为纯 JavaScript 应用。
- 全部品牌文案使用“寰语”，登录字段使用“账号”和“密码”。
- 保留 `POST /api/v1/auth/login` 及现有 Cookie、CSRF、角色跳转契约。
- 不增加注册、套餐、支付、找回密码、模拟提供商或模拟费用数据。
- 不使用境外字体 CDN；动效必须支持 `prefers-reduced-motion` 降级。
- 所有普通正文至少 4.5:1 对比度，大字、边框和焦点状态至少 3:1。

---

### Task 1: 建立设计变量和品牌图形组件

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/components/BrandLogo.vue`
- Create: `frontend/src/components/TranslationGlobe.vue`
- Test: `frontend/src/components/BrandLogo.test.ts`
- Modify: `frontend/src/styles/main.css`
- Modify: `frontend/index.html`

**Interfaces:**
- Produces: `BrandLogo` Vue 组件，接受 `compact?: boolean` 和 `subtitle?: string` props。
- Produces: `TranslationGlobe` Vue 组件，仅输出用户提供的装饰图形并使用 `aria-hidden="true"`。
- Produces: 语义化 CSS 变量，后续任务只通过变量读取主题色、间距、圆角和阴影。

- [ ] **Step 1: 编写品牌组件失败测试**

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BrandLogo from "./BrandLogo.vue";

describe("BrandLogo", () => {
  it("显示寰语品牌和可选副标题", () => {
    const wrapper = mount(BrandLogo, { props: { subtitle: "智能视频全球化工作台" } });
    expect(wrapper.text()).toContain("寰语");
    expect(wrapper.text()).toContain("智能视频全球化工作台");
  });
});
```

- [ ] **Step 2: 运行测试并确认组件不存在**

Run: `cd frontend && npm test -- src/components/BrandLogo.test.ts`
Expected: FAIL，提示无法解析 `BrandLogo.vue`。

- [ ] **Step 3: 创建变量和品牌组件**

`tokens.css` 至少定义：

```css
:root {
  color-scheme: dark;
  --color-canvas: #050b18;
  --color-surface: #071126;
  --color-surface-raised: #0b1730;
  --color-accent-cyan: #32b7ff;
  --color-accent-blue: #4778ff;
  --color-accent-violet: #8b52ff;
  --color-text: #f5f8ff;
  --color-text-muted: #a8b4cc;
  --radius-control: 10px;
  --radius-card: 16px;
  --radius-panel: 24px;
  --shadow-neon: 0 0 28px rgb(50 183 255 / 22%);
}
```

`BrandLogo.vue` 使用提供稿中的气泡翻译标识与真实文字；`TranslationGlobe.vue` 抽取提供 HTML 中的球体、路线、节点与四个功能标签。

- [ ] **Step 4: 引入变量并更新站点元数据**

`main.css` 首行引入 `./tokens.css`；`frontend/index.html` 使用 `#050b18` 主题色和“寰语｜LinguaSphere 智能视频全球化工作台”标题。

- [ ] **Step 5: 运行组件测试与类型检查**

Run: `cd frontend && npm test -- src/components/BrandLogo.test.ts && npm run typecheck`
Expected: PASS。

- [ ] **Step 6: 提交设计基础**

```bash
git add frontend/index.html frontend/src/styles frontend/src/components/BrandLogo.vue frontend/src/components/TranslationGlobe.vue frontend/src/components/BrandLogo.test.ts
git commit -m "feat: establish linguasphere visual system"
```

### Task 2: 重构真实 API 登录页

**Files:**
- Create: `frontend/src/views/auth/LoginView.test.ts`
- Modify: `frontend/src/views/auth/LoginView.vue`
- Modify: `frontend/src/styles/main.css`
- Modify: `frontend/src/views/auth/ForcePasswordView.vue`

**Interfaces:**
- Consumes: `BrandLogo` 和 `TranslationGlobe`。
- Consumes: `auth.login(loginName: string, password: string): Promise<void>`。
- Preserves: 管理员、运营成员和强制改密码跳转逻辑。

- [ ] **Step 1: 编写登录行为失败测试**

```ts
it("使用账号和密码调用真实 auth store", async () => {
  const wrapper = mount(LoginView, { global: { plugins: [router, pinia] } });
  await wrapper.get("#login-name").setValue("operator");
  await wrapper.get("#password").setValue("secret123");
  await wrapper.get("form").trigger("submit");
  expect(loginSpy).toHaveBeenCalledWith("operator", "secret123");
  expect(wrapper.text()).not.toContain("邮箱");
});
```

同文件增加密码显示按钮的 `aria-pressed`、加载按钮文案和错误 `role="alert"` 断言。

- [ ] **Step 2: 运行测试并确认当前页面结构不符合**

Run: `cd frontend && npm test -- src/views/auth/LoginView.test.ts`
Expected: FAIL，缺少新布局或密码切换行为。

- [ ] **Step 3: 实现参考图布局和真实登录交互**

`LoginView.vue` 使用 `auth.login(loginName.trim(), password)`，只把账号名写入 `localStorage` 的 `linguasphere.rememberedLoginName`，不保存密码。提交按钮文案为“登录工作台”，帮助文案为“无法登录？请联系公司系统管理员重置密码。”

- [ ] **Step 4: 同步强制修改密码页的品牌样式**

保留 `changePassword(currentPassword, newPassword)` 行为，仅更新品牌、面板、字段、按钮和焦点状态。

- [ ] **Step 5: 运行登录测试与完整前端测试**

Run: `cd frontend && npm test -- src/views/auth/LoginView.test.ts && npm test`
Expected: PASS。

- [ ] **Step 6: 提交登录页**

```bash
git add frontend/src/views/auth frontend/src/styles/main.css
git commit -m "feat: rebuild linguasphere login experience"
```

### Task 3: 拆分三文件登录视觉样板

**Files:**
- Create: `frontend/design-reference/index.html`
- Create: `frontend/design-reference/styles.css`
- Create: `frontend/design-reference/app.js`

**Interfaces:**
- Produces: `window.LINGUASPHERE_LOGIN_CONFIG = { apiBaseUrl: string, successPath: string }` 配置入口。
- Produces: `requestLogin(loginName: string, password: string): Promise<object>`，通过 `fetch` 请求真实 API。

- [ ] **Step 1: 从提供 HTML 拆分语义结构、样式和脚本**

`index.html` 只引用 `styles.css` 与 `app.js`，账号输入使用 `name="loginName" type="text" autocomplete="username"`，不存在 `email` 字段。

- [ ] **Step 2: 实现可配置真实请求**

```js
const config = Object.assign(
  { apiBaseUrl: "", successPath: "/" },
  window.LINGUASPHERE_LOGIN_CONFIG || {},
);

export async function requestLogin(loginName, password) {
  const response = await fetch(`${config.apiBaseUrl}/api/v1/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loginName, password }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "登录服务暂时不可用");
  return payload;
}
```

- [ ] **Step 3: 扫描模拟逻辑和邮箱残留**

Run: `rg -n "setTimeout|mock|邮箱|type=\"email\"|name=\"email\"" frontend/design-reference`
Expected: 无结果。

- [ ] **Step 4: 提交三文件样板**

```bash
git add frontend/design-reference
git commit -m "feat: split configurable login design reference"
```

### Task 4: 升级用户端与管理端公共外壳

**Files:**
- Modify: `frontend/src/components/AppSidebar.vue`
- Modify: `frontend/src/components/AppHeader.vue`
- Modify: `frontend/src/layouts/OperatorLayout.vue`
- Modify: `frontend/src/layouts/AdminLayout.vue`
- Modify: `frontend/src/styles/main.css`

**Interfaces:**
- Consumes: `BrandLogo` 与现有 `items` 导航数组。
- Preserves: `open` 移动导航状态、`logout()` 和路由标题。

- [ ] **Step 1: 在侧栏中使用寰语品牌组件**

`AppSidebar.vue` 用 `<BrandLogo subtitle="智能视频全球化工作台" />` 替换现有旧品牌区域，保留真实账号名、角色和退出按钮。

- [ ] **Step 2: 实现品牌化侧栏、顶栏和导航状态**

`main.css` 使用半透明深色表面、细蓝边界、当前导航左侧青蓝光标和可见键盘焦点；窄屏仍使用遮罩和抽屉。

- [ ] **Step 3: 运行类型检查与生产构建**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: PASS。

- [ ] **Step 4: 提交工作区外壳**

```bash
git add frontend/src/components/AppSidebar.vue frontend/src/components/AppHeader.vue frontend/src/layouts frontend/src/styles/main.css
git commit -m "feat: theme operator and admin application shells"
```

### Task 5: 统一用户端和管理端全部内容组件

**Files:**
- Modify: `frontend/src/styles/main.css`
- Modify when semantic wrappers are required: `frontend/src/views/operator/*.vue`
- Modify when semantic wrappers are required: `frontend/src/views/admin/*.vue`
- Modify: `frontend/src/components/StatePanel.vue`
- Modify: `frontend/src/components/StatusBadge.vue`
- Modify: `frontend/src/components/OneTimePasswordDialog.vue`
- Modify: `frontend/src/components/provider/*.vue`

**Interfaces:**
- Preserves: 所有视图的 API 调用、分页、筛选、表单提交、任务操作和真实空状态。
- Produces: 用户端较强的任务流光效与管理端较高的数据密度。

- [ ] **Step 1: 更新基础控件**

覆盖 `.card`、`.btn`、`.input`、`.select`、`.textarea`、`.badge`、`.data-table`、`.dialog-card`、`.state-panel` 的背景、边界、文字、悬停、焦点、禁用和错误状态，全部使用 `tokens.css` 变量。

- [ ] **Step 2: 升级用户端任务体验**

将 `.upload-zone`、`.language-option`、`.option-icon`、`.cost-box`、`.progress`、`.timeline`、`.subtask-card` 改为青蓝线路与节点语言，并保留文字状态和操作反馈。

- [ ] **Step 3: 升级管理端数据密度**

将 `.stat`、`.dashboard-grid`、`.compact-row`、`.health-list`、`.provider-card`、`.version-row`、`.filter-bar`、`.log-tabs` 调整为更弱发光、更强表格边界和更紧凑间距的管理视图。

- [ ] **Step 4: 验证无模拟文案或旧品牌残留**

Run: `rg -n "译界|Mock|mock_|demo" frontend/src frontend/index.html`
Expected: 仅允许测试文件中的技术性 mock，用户可见模板无匹配。

- [ ] **Step 5: 运行全套前端检查**

Run: `cd frontend && npm test && npm run typecheck && npm run lint && npm run build`
Expected: 全部 PASS。

- [ ] **Step 6: 提交全部页面升级**

```bash
git add frontend/src
git commit -m "feat: apply linguasphere neon system across workspaces"
```

### Task 6: 浏览器视觉、响应式和无障碍验收

**Files:**
- Create: `design-qa.md`
- Modify as issues require: `frontend/src/styles/main.css`
- Modify as issues require: affected Vue components

**Interfaces:**
- Consumes: 参考图 `codex-clipboard-268e5194-e17b-4f0e-af21-a0036e059653.png`。
- Produces: `design-qa.md` with `final result: passed`。

- [ ] **Step 1: 在内置浏览器打开真实应用**

打开 `http://127.0.0.1:5173/login`，确认页面来自正式 Vue 应用且浏览器控制台无错误。

- [ ] **Step 2: 执行登录主交互验收**

用键盘完成账号、密码、密码显示、记住账号和提交操作；验证空字段、后端错误和加载状态。

- [ ] **Step 3: 执行视口与对比度检查**

验证 320、768、1024、1440 和 1673×941 视口；运行 axe，要求无 serious/critical 违规。

- [ ] **Step 4: 执行同视口视觉对比并修复 P0-P2 问题**

将参考图与 1673×941 登录页截图同时检查，重点对比字号、双栏比例、地球位置、卡片大小、边框和光晕。

- [ ] **Step 5: 写入验收报告并运行最终检查**

`design-qa.md` 记录目标视口、主交互、响应式、axe 结果、已修复问题和 `final result: passed`。

Run: `cd frontend && npm test && npm run typecheck && npm run lint && npm run build`
Expected: 全部 PASS。

- [ ] **Step 6: 提交验收结果**

```bash
git add frontend design-qa.md
git commit -m "test: verify linguasphere responsive visual system"
```
