# 寰语视觉实现 QA

## 核验对象

- 参考截图：`C:\Users\SSS\AppData\Local\Temp\codex-clipboard-268e5194-e17b-4f0e-af21-a0036e059653.png`
- 参考 HTML：原始登录页视觉稿（未随仓库发布）
- Vue 实现：`frontend/src/views/auth/LoginView.vue`
- 独立拆分参考实现：`frontend/design-reference/index.html`、`styles.css`、`app.js`

## 对比基线

- 主题：深色霓虹
- 页面状态：未登录、账号和密码为空、密码隐藏
- 参考与实现视口：`1672 × 941`，1x 密度
- 全页同尺寸对比：`docs/design-qa/design-qa-comparison.png`
- 登录卡片同尺寸局部对比：`docs/design-qa/design-qa-login-card-comparison.png`
- Vue 实现原始截图：`docs/design-qa/design-qa-implementation-1672x941.png`

## 第一轮发现与修正

1. **P2 / 布局**：桌面页顶部留白造成品牌、主标题和登录卡片整体下移。将桌面壳层顶部留白收紧，并让卡片高度随视口在 610–680px 间响应。
2. **P2 / 状态**：空表单时按钮被业务禁用条件压暗，与参考图的主 CTA 不一致。改为仅请求中禁用，空值继续交给浏览器必填校验。
3. **P2 / 文案与换行**：标题说明中的“视频”导致桌面换行位置偏移。调整为更适合全产品范围的“AI 翻译平台”。
4. **P2 / 色彩**：背景环线与卡片表面偏亮。降低装饰环透明度并加深面板渐变。
5. **P2 / 桌面滚动**：大屏登录页出现无意义滚动。固定桌面壳层高度，平板与移动端恢复自然滚动。

## 第二轮核验结果

- **布局与间距**：1672px 视口下，登录卡片左边缘与参考一致；顶部约 4px 差异，属于抗锯齿和边框发光范围。标题、表单字段、CTA 与底部安全提示保持同一视觉节奏。
- **字体与层级**：使用系统中文无衬线字体栈；标题、正文、标签和按钮的字号、字重、行高及换行与参考一致。
- **颜色与表面**：青蓝到紫色品牌渐变、边框发光、深蓝玻璃面板、输入框和 CTA 状态均由 `tokens.css` 变量驱动。
- **图像与图标**：品牌标识和地球连线来自提供的参考 HTML 源资产；操作图标统一使用项目现有图标库，没有占位图或 emoji。
- **内容**：按业务边界将“邮箱地址”改为“账号”，将“忘记密码”改为管理员重置说明；这是有意的产品文案差异。
- **交互**：密码显示/隐藏按钮可用并正确更新按压状态；空表单提交触发原生必填校验并聚焦账号字段；没有发起伪造登录。
- **API**：Vue 登录继续调用现有真实 `auth.login(loginName, password)`；独立 `app.js` 使用可配置的 `fetch` API 地址，没有模拟延时或演示账号。
- **响应式**：已在 1024×768、768×1024、390×844 浏览器视口复核，未发现重叠、裁切、不可触达控件或破坏层级的换行。
- **无障碍**：表单具备可见标签、语义按钮、必填属性、焦点样式、`aria-pressed`、状态提示与 reduced-motion 支持；移动端主要控件满足实用触控尺寸。
- **浏览器日志**：只有 Vite 连接与热更新调试日志，错误日志为 0。
- **工程质量**：18 个前端测试通过；TypeScript 类型检查、ESLint 和生产构建全部通过。
- **用户端与管理端**：共享品牌、侧边栏、顶部栏、卡片、表单、表格、状态徽标和弹窗的同一套深色霓虹设计系统；业务路由和现有数据逻辑未改为模拟实现。

## 证据截图

- `docs/design-qa/design-qa-1024x768.png`
- `docs/design-qa/design-qa-768x1024.png`
- `docs/design-qa/design-qa-390x844.png`

## 内部角色边界与管理端布局复核（2026-09-02）

### 缺陷参考

- 运营端费用预估：`C:\Users\SSS\AppData\Local\Temp\codex-clipboard-437e344c-79f4-46f1-ac64-18a1facc60b2.png`
- 管理端重复高亮：`C:\Users\SSS\AppData\Local\Temp\codex-clipboard-e4228772-43e3-4ee4-bb09-fab5a4b5d96a.png`
- 运营端重复高亮：`C:\Users\SSS\AppData\Local\Temp\codex-clipboard-3f74d008-bc78-468b-b894-eafe3e0513e3.png`
- 管理端非对称留白：`C:\Users\SSS\AppData\Local\Temp\codex-clipboard-5d6de9c2-e52c-4428-836b-6627817a5944.png`

### 修正结果

1. 运营端新建翻译、翻译记录和详情不再显示预估费用、实际费用或金额；费用数据仍保留在管理员专用的“调用费用”页面。
2. 首次登录修改密码统一调整为至少 6 位，不限制字符类型；前端约束、后端校验和接口测试保持一致。
3. 管理员导航删除“进入运营端”，管理员端只保留运行概览、账号、任务、接口、费用和日志六项管理能力。
4. 侧栏高亮改为由路由 `navItem` 元数据精确控制；`/admin/accounts` 与 `/translations/new` 实测均只有一个活动项。
5. 修复深色主题样式覆盖侧栏固定定位的问题，消除“侧栏占位 + 主内容左外边距”造成的重复 256px 偏移；管理端内容区现从侧栏右缘连续开始。

### 浏览器与工程复核

- `1920 × 1080`：侧栏宽 256px，主内容区从 x=256 延伸至视口右缘，页面无横向溢出，活动导航数为 1。
- `1440 × 900`：侧栏宽 256px，主内容区宽 1184px，左右内容内边距对称，活动导航数为 1。
- `390 × 844`：侧栏收起至视口外，主内容占满可用宽度，卡片表格转为移动布局，活动导航数为 1。
- 前端：10 个测试文件、18 个测试全部通过；TypeScript、ESLint、Vite 生产构建全部通过。
- 后端：33 个单元测试通过；认证接口 14 个测试通过，1 个依赖独立 MySQL/Redis 测试环境的真实 HTTP 用例按环境要求未执行。

### 新增证据

- 修复前后同屏对比：`docs/design-qa/design-qa-admin-spacing-comparison.png`
- 桌面 1920：`docs/design-qa/design-qa-admin-aligned-1920x1080.png`
- 桌面 1440：`docs/design-qa/design-qa-admin-1440x900.png`
- 移动端 390：`docs/design-qa/design-qa-admin-mobile-390x844.png`

final result: passed
