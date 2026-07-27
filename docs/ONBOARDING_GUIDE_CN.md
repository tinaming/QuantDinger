# ChanQuant 新人入门指南 —— AI 驱动的量化开发

> **核心理念**：在 ChanQuant 项目中，AI 不是辅助工具，而是你的主力搭档。
> 写好 Rule、用好 Skills、让 AI 理解项目上下文，是高效开发的关键。

---

## 目录

1. [环境搭建（30 分钟）](#1-环境搭建)
2. [AI 工具配置（核心，1 小时）](#2-ai-工具配置)
3. [理解项目架构（2 小时）](#3-理解项目架构)
4. [跑通第一个策略（1 小时）](#4-跑通第一个策略)
5. [写你自己的 Skills（进阶）](#5-写你自己的-skills)
6. [协作规范](#6-协作规范)
7. [常见问题](#7-常见问题)

---

## 1. 环境搭建

### 必装软件

| 软件 | 用途 | 链接 |
|------|------|------|
| Python 3.12 | 后端运行时 | python.org |
| Git | 版本控制 | git-scm.com |
| VS Code / Qoder IDE | 编辑器 + AI 集成 | qoder.com |
| Docker Desktop | 全栈部署 | docker.com |

### 快速启动

```powershell
# 1. 克隆仓库
git clone https://gitee.com/quant_4102/chanquant.git
cd chanquant

# 2. 配置环境变量
cd backend_api_python
Copy-Item env.example .env
# 编辑 .env，至少配置: SECRET_KEY, DATABASE_URL, LLM_PROVIDER

# 3. Docker 一键启动（推荐）
cd ..
docker compose up -d

# 4. 访问平台
# 浏览器打开 http://localhost:8888
# 默认账号: chanquant / 123456
```

---

## 2. AI 工具配置

**这是整份指南最重要的部分。** 花 1 小时配好 AI 环境，后续开发效率提升 10 倍。

### 2.1 理解三层 AI 协作架构

```
┌─────────────────────────────────────────┐
│  Layer 1: Rules（规则层）                │
│  AGENTS.md — 项目级的 AI 行为规范        │
│  告诉 AI：项目是什么、怎么改、什么不能碰  │
├─────────────────────────────────────────┤
│  Layer 2: Skills（技能层）               │
│  .qoder/skills/ — 可复用的 AI 任务模板   │
│  告诉 AI：遇到特定场景该怎么做            │
├─────────────────────────────────────────┤
│  Layer 3: MCP Tools（工具层）            │
│  MCP Server — AI 可直接调用的 API 工具   │
│  让 AI：查行情、跑回测、管理策略          │
└─────────────────────────────────────────┘
```

### 2.2 Rule 配置：AGENTS.md

项目根目录的 `AGENTS.md` 是 AI 的"行为手册"。它告诉 AI：

- **项目架构**：Flask 后端、PostgreSQL、Vue 前端的关系
- **代码规范**：文件在哪、怎么命名、测试怎么跑
- **红线禁区**：不能随便改的模块、不能绕过的安全检查

**你需要做的**：
1. 通读 `AGENTS.md`，理解项目结构
2. 随着你深入了解项目，**持续补充** AGENTS.md
3. 每次发现 AI 犯的重复错误 → 加一条 Rule 避免

**Rule 写作技巧**：

```markdown
# 好的 Rule —— 具体、可执行
## 数据源适配器
新增数据源必须放在 `app/data_sources/` 下，继承 BaseDataSource，
实现 fetch_ohlcv() 方法，并注册到 factory.py。
参考现有模块：`app/data_sources/crypto.py`

# 差的 Rule —— 模糊、AI 无法执行
## 写好代码
写代码要规范，要加注释，要测试。
```

### 2.3 Skills：AI 的可复用技能

Skills 是比 Rule 更细粒度的指导。每个 Skill 是一个"任务剧本"，告诉 AI 遇到特定场景该一步步怎么做。

**项目已有的 Skills**：

| Skill | 位置 | 用途 |
|-------|------|------|
| `chat-diagnosis` | `.qoder/skills/chat-diagnosis/` | 诊断 AI 聊天性能问题 |
| `quantdinger-agent-workflow` | `.cursor/skills/quantdinger-agent-workflow/` | 代码编辑工作流（skill 目录名保留原名） |
| `aicoin-market` | `.qoder/skills/coinos-skills/` | 查行情、K线、资金费率 |
| `aicoin-trading` | `.qoder/skills/coinos-skills/` | CEX 下单交易 |
| `aicoin-freqtrade` | `.qoder/skills/coinos-skills/` | Freqtrade 策略/回测 |
| `aicoin-hyperliquid` | `.qoder/skills/coinos-skills/` | 链上鲸鱼/大户分析 |
| `aicoin-onchain` | `.qoder/skills/coinos-skills/` | 链上 DEX swap |
| `aicoin-account` | `.qoder/skills/coinos-skills/` | 交易所账户管理 |

**Skill 文件结构**：

```
.qoder/skills/my-skill/
├── SKILL.md          # 核心：AI 阅读的任务指南
├── scripts/          # 可选：AI 可调用的脚本
│   └── do-something.mjs
└── lib/              # 可选：共享库
    └── helper.mjs
```

### 2.4 MCP Server：AI 的工具箱

MCP (Model Context Protocol) 让 AI 直接调用后端 API，无需你手动操作。

**配置 MCP**（`.cursor/mcp.json` 或 Qoder 的 MCP 设置）：

```json
{
  "mcpServers": {
    "quantdinger": {
      "command": "quantdinger-mcp",
      "env": {
        "CHANQUANT_BASE_URL": "http://localhost:5000",
        "CHANQUANT_AGENT_TOKEN": "你的agent_token"
      }
    }
  }
}
```

**获取 Agent Token**：
1. 登录平台 → 个人中心 → My Agent Token
2. 创建一个带 R（读取）+ B（回测）权限的 Token
3. 复制 Token 填入 MCP 配置

**配好后 AI 可以直接**：
- `get_klines` — 拉取 K 线数据
- `submit_backtest` — 提交回测任务
- `list_strategies` — 查看策略列表
- `save_indicator` — 保存指标代码
- `regime_detect` — 市场状态检测

### 2.5 推荐的 LLM 配置

在 `backend_api_python/.env` 中配置 AI 提供商：

```bash
# 推荐方案（按优先级）
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-xxx

# 备选
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx

# 国内备选（阿里云百炼）
LLM_PROVIDER=bailian
DASHSCOPE_API_KEY=sk-xxx
```

---

## 3. 理解项目架构

### 30 秒架构速览

```
浏览器/MCP Client
       │
       ▼
  Nginx (:8888) ──► Vue SPA（前端页面）
       │
       ▼
  Flask API (:5000)
       │
       ├── /api/...           人类用户 API（JWT 登录）
       │
       └── /api/agent/v1/...  AI Agent API（Token 认证）
              │
              ▼
        Service Layer ← 所有业务逻辑在这里
```

### 关键目录速查

| 你想做什么 | 看这个目录 |
|-----------|-----------|
| 改 API 路由 | `app/routes/` |
| 改业务逻辑 | `app/services/` |
| 加新数据源 | `app/data_sources/` |
| 改 AI 聊天 | `app/routes/ai_chat.py` + `app/services/llm.py` |
| 加新交易所 | `app/services/exchange_execution.py` |
| 写策略脚本 | `docs/examples/` 参考模板 |
| 改数据库表 | `migrations/init.sql` |

### 两种策略模式

| 模式 | 适合场景 | 难度 |
|------|---------|------|
| **IndicatorStrategy** | 技术指标组合（均线、RSI、MACD 等） | 入门级 |
| **ScriptStrategy** | 复杂逻辑（网格、套利、事件驱动） | 进阶 |

**入门建议**：从 IndicatorStrategy 开始，它就是一个返回 DataFrame 的 Python 函数，加上 `buy`/`sell` 布尔列即可。

---

## 4. 跑通第一个策略

### 4.1 在平台 UI 中操作

1. 登录平台 → **Indicator IDE**
2. 输入以下双均线策略代码：

```python
# @param sma_short (int, 5, 50, 10) 短期均线周期
# @param sma_long (int, 20, 200, 30) 长期均线周期

df = df.copy()
df['sma_short'] = df['close'].rolling(window=sma_short).mean()
df['sma_long'] = df['close'].rolling(window=sma_long).mean()

prev_short = df['sma_short'].shift(1)
prev_long = df['sma_long'].shift(1)

df['buy'] = (prev_short <= prev_long) & (df['sma_short'] > df['sma_long'])
df['sell'] = (prev_short >= prev_long) & (df['sma_short'] < df['sma_long'])

output = df[['buy', 'sell']].dropna(how='all')
```

3. 选择 **BTC/USDT**，时间周期选 **1H**
4. 点击运行 → 观察买卖信号
5. 点击回测 → 查看收益曲线

### 4.2 用 AI 辅助开发策略

**对话示例**（在 Qoder/Cursor 中）：

> "帮我写一个 RSI + 布林带的 IndicatorStrategy，RSI < 30 且价格触及布林带下轨时买入"

AI 会参考 `AGENTS.md` 和 `docs/STRATEGY_DEV_GUIDE_CN.md` 自动生成符合规范的代码。

> "用 MCP 工具把这个指标保存到平台，然后跑一个 BTC/USDT 1H 的回测"

AI 会调用 `save_indicator` → `submit_backtest` → 等待结果 → 返回报告。

---

## 5. 写你自己的 Skills

**这是提升团队协作效率的关键。** 每当你发现自己在重复做某类任务，就写一个 Skill。

### 5.1 Skill 的 SKILL.md 模板

```markdown
---
name: my-new-skill
description: >-
  一句话描述这个 Skill 做什么。
  Trigger: '触发词1', '触发词2', '触发词3'
---

# Skill 名称

## 适用场景
当用户需要 XXX 时使用此 Skill。

## 执行步骤

### Step 1: 做什么
具体指令...

### Step 2: 做什么
具体指令...

## 关键文件
| 文件 | 用途 |
|------|------|
| `path/to/file.py` | 这个文件做什么 |

## 注意事项
- 不要做 XXX
- 必须做 YYY
```

### 5.2 推荐新写的 Skills

#### Skill 1: `data-source-creator` — 新建数据源适配器

```
触发场景：需要接入新的行情数据提供商
内容：参考 data_sources/factory.py 的工厂模式，
      指导 AI 创建符合规范的数据源模块
```

#### Skill 2: `strategy-debugger` — 策略调试助手

```
触发场景：策略回测结果异常、信号不符合预期
内容：指导 AI 检查数据质量、信号逻辑、参数范围，
      输出诊断报告
```

#### Skill 3: `test-writer` — 自动写测试

```
触发场景：需要给某个 service 或 route 补测试
内容：参考 tests/conftest.py 的 fixture 模式，
      生成符合项目规范的 pytest 测试
```

#### Skill 4: `indicator-reviewer` — 指标代码审查

```
触发场景：提交指标代码前的 review
内容：检查常见陷阱（未来函数、look-ahead bias、
      边缘触发 vs 持续触发），给出修改建议
```

#### Skill 5: `api-endpoint-creator` — 新增 API 端点

```
触发场景：需要添加新的 REST API
内容：指导使用 flask-smorest 蓝图模式，
      包含 Schema 定义、权限检查、错误处理
```

### 5.3 Skill 编写最佳实践

1. **描述要精确**：`description` 字段决定 AI 何时调用这个 Skill，写清楚触发词
2. **步骤要可执行**：不要写"分析代码"，要写"检查 X 文件的 Y 函数是否满足 Z 条件"
3. **引用关键文件**：AI 会读取这些文件来获取上下文
4. **包含反面例子**：明确告诉 AI "不要做 XXX" 往往比 "要做 YYY" 更有效
5. **保持更新**：项目演进后，及时更新 Skill 中的文件路径和逻辑

---

## 6. 协作规范

### Git 工作流

```powershell
# 1. 从主分支拉自己的 feature 分支
git checkout feat/clean-merge
git pull
git checkout -b feat/你的名字-功能描述

# 2. 开发过程中频繁提交
git add -A
git commit -m "feat: 描述你做了什么"

# 3. 推送到 Gitee
git push -u origin feat/你的名字-功能描述

# 4. 在 Gitee 上创建 PR，指定 reviewer
```

### AI 辅助 Code Review

提交 PR 前，可以让 AI 先 review 你的代码：

> "Review 一下我的改动，重点检查是否有安全问题、性能问题、和现有架构不一致的地方"

### 提交前检查清单

- [ ] `pytest` 全部通过
- [ ] 没有提交 `.env`、API Key 等敏感信息
- [ ] 新增的 API 有对应的 OpenAPI Schema
- [ ] 策略代码没有未来函数（look-ahead bias）

---

## 7. 常见问题

### Q: AI 生成的代码不符合项目规范？

**A**: 说明 `AGENTS.md` 的 Rule 不够具体。把具体的规范加进去，比如：
- 文件命名规则
- 函数签名格式
- 错误处理方式

### Q: AI 不知道某个模块的存在？

**A**: 在 AGENTS.md 的架构部分加上模块说明，或者创建一个专门的 Skill 描述该模块。

### Q: MCP 工具调用失败？

**A**: 
1. 确认后端在运行：`docker compose ps`
2. 确认 Agent Token 有效：平台 → 个人中心 → My Agent Token
3. 确认 MCP 配置正确：检查 `.cursor/mcp.json` 或 Qoder 设置

### Q: 怎么让 AI 帮我做更复杂的事？

**A**: 把复杂任务拆成多步，每一步用对话驱动：
1. "先帮我分析这个策略的逻辑"
2. "然后帮我写单元测试"
3. "最后帮我跑回测并分析结果"

---

## 快速参考卡

| 我想... | 用这个工具 |
|---------|-----------|
| 查 BTC 价格 | AI 对话 + aicoin-market Skill |
| 写一个技术指标 | Indicator IDE + AI 辅助 |
| 回测策略 | 平台 UI 或 MCP `submit_backtest` |
| 下单交易 | aicoin-trading Skill（需确认） |
| 看鲸鱼动向 | aicoin-hyperliquid Skill |
| 改后端代码 | VS Code + AI + AGENTS.md |
| 写测试 | AI + `tests/` 参考 + test-writer Skill |
| 部署上线 | `docker compose up -d --build` |

---

> **记住**：Rule 写得越好，AI 理解得越准；Skill 写得越多，AI 能力越强。
> 投入 1 小时写 Rule 和 Skill，能节省 100 小时的重复工作。
