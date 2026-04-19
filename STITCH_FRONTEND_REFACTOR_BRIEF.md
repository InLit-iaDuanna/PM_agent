# Stitch Frontend Refactor Brief

这份文档是给 Stitch 的前端重构说明，不是功能 PRD。目标是让 Stitch 先理解当前前端的产品气质、视觉语言、页面角色和技术边界，再进行重构。

## 1. 项目是什么

这是一个 PM 研究工作台，不是通用后台管理系统。

核心用户路径：

1. 用户从研究指挥台发起一个研究任务
2. 系统把问题拆成多个研究子任务
3. 系统收集证据、生成结构化结论、合成研究报告
4. PM 再基于报告和证据继续追问
5. 后续补充研究会继续回流到报告体系

所以前端的定位不是“表单 + 列表 + 图表”，而是：

- 研究指挥台
- 情报工作室
- 可交付的研究阅读器
- 可追问的 PM 决策界面

一句话定义：

**这是一个带咨询交付气质的 PM 研究操作系统，而不是一个普通 SaaS 后台。**

## 2. 当前前端视觉总结

### 2.1 核心气质

当前前端最有价值的不是某个单独组件，而是整套气质：

- 温暖、纸面感、研究桌面感
- 不是冷冰冰的数据后台
- 不是 AI 产品常见的紫色、黑色、赛博风
- 不是“泛化设计模板”
- 更像研究工作室、分析台、顾问报告工作台

### 2.2 视觉关键词

请把下面这些词当作视觉方向的源描述：

- editorial
- paper-like
- warm
- calm
- intentional
- research studio
- dossier
- mission control
- not generic admin

### 2.3 当前设计语言

当前前端已经形成了一套比较明确的视觉系统：

- 背景是暖纸色，不是纯白
- 面板是半透明纸面/玻璃感，不是重阴影卡片堆叠
- 标题有明显编辑感和交付感
- 数据区域仍保留专业工具属性，但要嵌入更高级的整体壳层
- 动效克制，只做轻微的进入、浮起、信号反馈，不做花哨炫技

当前全局视觉基调主要来自：

- `apps/web/app/globals.css`
- `apps/web/app/layout.tsx`

其中已经存在的关键设计 token 很重要：

- 暖纸背景：`--bg`, `--bg-strong`
- 面板系统：`--panel`, `--panel-strong`, `--panel-muted`
- 主强调色：`--accent`
- 辅助暖色：`--warm`
- 阴影体系：`--shadow-sm` 到 `--shadow-xl`
- 圆角体系：`--r-sm` 到 `--r-2xl`

这些 token 可以升级，但不要推翻成另一种完全无关的视觉语系。

## 3. 字体与排版气质

当前字体组合很关键：

- 正文：`Noto Sans SC`
- 标题：`Playfair Display`

这形成了一个很重要的效果：

- 正文是专业、稳定、可读的中文工作台
- 标题有一点编辑感、报告感、品牌感

这个方向值得保留，不建议重构成：

- 通用 `Inter` 后台风
- 过于机械的纯系统字体风
- 太互联网运营、太电商、太营销的风格

## 4. 页面角色分层

不是所有页面都应该长得一样。当前前端已经隐约形成了页面层级，这个层级要保留并强化。

### 4.1 首页

文件：

- `apps/web/features/research/components/home-dashboard-refactored.tsx`

角色：

- 研究指挥台
- Command Deck
- 进入系统后的第一层产品气质展示

这个页面现在是最接近目标方向的页面之一。

应该继续强化的感觉：

- 研究任务发射台
- 情报与工作流入口
- 高级但不浮夸

### 4.2 新建研究页

文件：

- `apps/web/features/research/components/new-research-form-refactored.tsx`

角色：

- Research Launcher
- 编排器
- 不是普通表单页

这个页面也已经很接近目标方向。

应该保留：

- 左侧步骤感
- 当前草稿摘要
- 环境状态
- 研究命令优先于普通字段输入

### 4.3 任务执行页

文件：

- `apps/web/features/research/components/job/job-page.tsx`
- `apps/web/features/research/components/job/job-overview-tab.tsx`

角色：

- 作战中枢
- 研究 mission control
- 运行态工作台

这里已经有比较好的“工作中”气质，但还可以更统一、更精炼。

### 4.4 证据页 / 任务细节页

文件：

- `apps/web/features/research/components/evidence-explorer.tsx`
- `apps/web/features/research/components/task-detail-panel.tsx`

角色：

- 高密度分析台
- 工具型页面

这类页面允许更工具化，但不能突然退化成普通 CRUD 表格后台。

当前问题是：

- 信息很全
- 但视觉密度略高
- 和首页/启动页的“高级壳层气质”有一点断层

### 4.5 报告页

文件：

- `apps/web/features/research/components/research-report-page.tsx`

角色：

- 研究交付件阅读器
- 版本化报告中心
- 决策阅读入口

这个页面应该更像“可交付报告阅读器”，而不是“只是把 markdown 显示出来”。

## 5. 必须保留的前端产品方向

以下不是建议，是重构时必须保留的产品认知。

### 5.1 必须保留 Chinese-first

这是中文优先产品，不是英文后台的汉化版。

要求：

- 主文案和主要导航继续保持中文优先
- 页面语义要适合中文阅读
- 信息密度要考虑中文环境下的节奏

### 5.2 必须保留“研究工作台”而不是“数据后台”

不要把整个产品重构成以下任一种：

- 通用 BI 仪表盘
- 表格驱动后台
- 传统项目管理工具
- 通用 AI chat app

### 5.3 必须保留“报告交付感”

用户最终拿到的不只是数据，而是：

- 证据
- 结论
- 报告
- 可追问的研究上下文

因此整体视觉必须能够支撑“研究交付件”的感觉。

### 5.4 必须保留“任务编排感”

研究不是单页输入即完成，而是一个编排过程：

- 选命令
- 配边界
- 运行任务
- 看证据
- 看报告
- 继续追问

前端不能丢失这种 orchestration 感。

## 6. 可以大胆重构的地方

下面这些地方可以颠覆性重构，只要不破坏产品语义和接口契约。

### 6.1 页面布局

可以重构：

- 首页布局
- 新建研究页布局
- Job 页头部布局
- Evidence 页信息组织方式
- Report 页阅读结构

### 6.2 卡片系统

可以重构：

- 卡片比例
- 卡片层级
- 卡片分区方式
- 数据摘要模块的视觉形式

### 6.3 导航与信息层级

可以重构：

- tabs 的视觉样式
- 页面区块优先级
- overview / evidence / report / chat 的承接关系

### 6.4 视觉强化

可以强化：

- 编辑感标题
- 纸面感背景
- 研究桌面纹理
- 轻微动效
- 报告感阅读体验

## 7. 不要做成什么样

以下是明确不希望 Stitch 做出来的结果。

### 7.1 不要做成通用 shadcn SaaS 后台

如果重构后的页面看起来像“任何 B2B 工具都能套的模板”，就是失败。

### 7.2 不要做成 AI slop landing page

不要变成：

- 大面积渐变
- 漂亮但没信息层级
- 视觉噪音很强
- 读起来没有工作感

### 7.3 不要做成深色赛博风

当前产品的成熟方向不是：

- dark neon
- purple AI
- terminal hacker

### 7.4 不要牺牲分析页面的可读性

Evidence 和任务细节页虽然可以更漂亮，但不能为了“设计感”牺牲：

- 过滤效率
- 信息可扫读性
- 研究透明度
- 证据可追溯性

## 8. 当前视觉最值得继承的部分

如果要找“风格源文件”，优先参考这些：

- `apps/web/app/globals.css`
- `apps/web/app/layout.tsx`
- `apps/web/features/research/components/home-dashboard-refactored.tsx`
- `apps/web/features/research/components/new-research-form-refactored.tsx`

如果要找“执行态页面”的结构源文件，参考这些：

- `apps/web/features/research/components/job/job-page.tsx`
- `apps/web/features/research/components/job/job-overview-tab.tsx`
- `apps/web/features/research/components/evidence-explorer.tsx`
- `apps/web/features/research/components/task-detail-panel.tsx`
- `apps/web/features/research/components/research-report-page.tsx`

如果要找“全局壳层”的参考文件，参考这些：

- `apps/web/features/shell/top-bar.tsx`
- `apps/web/features/shell/status-bar.tsx`

## 9. 当前视觉问题

重构时应重点解决这些问题。

### 9.1 首页和任务页之间有气质断层

首页和新建页已经比较有“研究工作室”的气质，但进入 job / evidence / task detail 后，页面会更像传统工具页。

目标：

- 让运行态页面也拥有同一套品牌壳层
- 但不牺牲工具效率

### 9.2 证据页信息密度高，但视觉组织还可以更聪明

当前证据页功能完整，但可以继续优化：

- 第一眼更清楚
- 筛选器更像分析工具
- 证据卡片更有引用感和层级感

### 9.3 报告页应更像交付件，不只是系统页面

报告页需要更强的：

- 阅读仪式感
- 版本感
- 决策阅读感
- 引用感

### 9.4 数据组件和品牌壳层之间还有统一空间

有些局部区域已经很高级，有些地方还是偏通用组件感。

目标不是统一成“全都很花”，而是统一成：

- 同一个产品世界观
- 同一种工作语境

## 10. 技术边界

Stitch 在重构时请遵守这些边界。

### 10.1 不要改后端契约

不要擅自重构：

- API 数据结构
- SSE 逻辑
- 类型契约
- 研究流程语义

### 10.2 优先在现有前端架构内重构

当前前端基础：

- Next.js
- React
- `@pm-agent/ui` 共享组件
- `@tanstack/react-query`

可扩展 `packages/ui`，但不要把整个项目推翻成另一套前端体系。

### 10.3 保持现有核心路由语义

需要继续支撑的核心页面：

- `/`
- `/research/new`
- `/research/jobs/[jobId]`
- `/research/jobs/[jobId]/report`
- `/settings/runtime`

### 10.4 保持研究工作流语义

前端要继续清楚表达这些对象：

- workflow command
- task
- evidence
- claims
- report versions
- PM chat

## 11. 共享组件层说明

当前共享 UI 组件在这里：

- `packages/ui/src/index.ts`

已暴露的基础组件包括：

- badge
- button
- card
- input
- progress-bar
- select
- textarea
- sidebar
- sheet
- skeleton
- tabs
- toast
- collapsible
- step-indicator
- timeline
- tooltip
- animated-card
- read-progress-bar

可以继续扩充这层，但新视觉应尽量沉淀成共享组件能力，而不是只在单页写一次性样式。

## 12. 我希望 Stitch 交付什么

理想的重构结果不是“换皮”，而是下面这些结果：

### 12.1 视觉目标

- 更统一的研究工作室气质
- 更强的报告交付感
- 更高的辨识度
- 更成熟的中文产品气质

### 12.2 产品目标

- 首页更像研究指挥台
- 新建研究页更像任务编排器
- Job 页更像 mission control
- Evidence 页更像分析台
- Report 页更像正式交付阅读器

### 12.3 交互目标

- 首屏信息层级更清楚
- 重信息页面更易读
- 页面切换之间的气质连续
- 用户更容易理解“从命令到报告”的路径

## 13. 可直接给 Stitch 的一句话任务描述

你可以把下面这段直接当作对 Stitch 的任务说明：

> 请基于当前代码库重构前端，但不要把它做成通用 SaaS 后台。这个产品是一个中文优先的 PM 研究工作台，整体气质应该像研究工作室、情报台、可交付报告系统，而不是普通管理平台。请保留当前暖纸面、编辑感、研究桌面式的视觉方向，重点提升 job / evidence / report 等运行态页面，让它们和首页、新建研究页一样有统一的产品气质。可以大胆重构布局和组件层次，但不要破坏现有路由、API 契约、研究流程语义和核心信息结构。

## 14. 额外提醒

如果 Stitch 只能记住一件事，那就是：

**请沿着“研究工作室 + 报告交付系统”的方向重构，而不是沿着“通用后台”方向重构。**
