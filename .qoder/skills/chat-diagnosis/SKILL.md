---
name: chat-diagnosis
description: >-
  诊断 ChanQuant AI Copilot 聊天性能与准确性问题。追踪从用户消息到 LLM 响应的完整管线，
  识别 intent 分类、enrich、LLM 调用各环节的耗时与准确性问题。
  Trigger: '聊天慢', '第二条消息不准', 'chat slow', 'chat diagnosis', 'AI聊天诊断'
---

# AI Copilot 聊天诊断

## 适用场景

当用户反馈以下问题时使用此 skill：
- AI 聊天响应慢
- 第二条/后续消息不准确
- 多轮对话上下文丢失
- intent 分类错误

## 架构：聊天管线全流程

```
用户消息 POST /chat/message (或 /chat/message/stream)
    │
    ├─ 1. DB Session Load        (~10ms)
    │     _get_session → _restore_session_context
    │
    ├─ 2. Intent Classification  (~2-5s, LLM call #1)
    │     新 session: _get_or_classify_agent_intent (LLM)
    │     旧 session: _classify_intent_with_session (LLM + 历史继承)
    │
    ├─ 3. Context Enrich         (~2-10s)
    │     新 session (full):
    │       _build_market_snapshot  → 3x K-line fetch (1H/4H/1D)
    │       _build_research_context → news search + macro lookup
    │     旧 session (lightweight, _enrich_context_followup):
    │       仅在用户明确要求时拉取市场数据
    │
    ├─ 4. Build LLM Messages     (~5ms)
    │     system prompt + history (12轮) + user message
    │
    ├─ 5. LLM Response           (~3-15s, LLM call #2)
    │     call_llm_api (JSON mode) 或 stream_llm_api
    │
    └─ 6. DB Write + Return      (~10ms)
```

## 诊断步骤

### Step 1: 检查 timing 日志

后端已内置分步计时日志，搜索关键字：

```powershell
# 非流式端点
Select-String -Path "backend_api_python/logs/app.log" -Pattern "\[chat_timing\]" | Select-Object -Last 10

# 流式端点
Select-String -Path "backend_api_python/logs/app.log" -Pattern "\[chat_stream_timing\]" | Select-Object -Last 10
```

日志格式：
```
[chat_timing] total=12.3s session=0.0s intent=3.2s enrich=4.1s build=0.0s llm=5.0s | follow_up=True intent=market_analysis
```

### Step 2: 判断瓶颈环节

| 环节 | 正常耗时 | 异常阈值 | 常见原因 |
|------|---------|---------|---------|
| session | <50ms | >200ms | DB 连接池耗尽 |
| intent | 1-5s | >8s | LLM provider 慢/超时 |
| enrich | <1s (follow-up) | >3s | 未走轻量路径, news search 卡住 |
| enrich | 2-5s (new) | >10s | K-line fetch 超时, search API 慢 |
| build | <50ms | >200ms | history 过大 |
| llm | 3-15s | >20s | prompt 过长, model 过载 |

### Step 3: 验证"第二条消息不准"

常见根因清单：

1. **Intent 被错误继承**
   - 检查 `intent` 字段是否为上一轮的 intent
   - 如果用户明确切换话题但 intent 被继承 → 检查 `_classify_intent_with_session` 中的关键词排除列表

2. **research_context 未注入**
   - follow-up 用轻量 enrich，不注入 research_context
   - 如果用户第二条消息需要市场数据但未被识别 → 检查 `_enrich_context_followup` 的 `needs_fresh_data` 关键词

3. **history 截断**
   - `_build_llm_messages` 只传最近 12 轮
   - 每条历史消息截断到 4000 字符
   - 如果第一条回复很长（如完整缠论分析），可能被截断

4. **working memory 未更新**
   - `_build_session_working_memory` 从历史中提取 known_fields
   - 如果第一条提到了 timeframe，第二条换了 → 检查 `_extract_session_known_fields` 的 regex 是否匹配

### Step 4: 快速修复验证

对常见问题，可以直接在后端测试：

```python
# 测试 intent 分类
from app.routes.ai_chat import _classify_agent_intent, _fallback_agent_intent
result = _fallback_agent_intent("换到日线看看", False, {"symbol": "BTC", "market": "crypto"})
print(result)  # 检查 fallback intent 是否合理
```

## 关键文件

| 文件 | 用途 |
|------|------|
| `backend_api_python/app/routes/ai_chat.py` | 聊天路由 + 全部管线逻辑 |
| `backend_api_python/app/services/ai_copilot_store.py` | Session/Message 持久化 |
| `backend_api_python/app/services/llm.py` | LLM 调用 (call_llm_api / stream_llm_api) |
| `backend_api_python/app/services/search.py` | 新闻搜索 (8个渠道) |
| `backend_api_python/logs/app.log` | timing 日志输出位置 |

## 已实现的优化

1. **消除 double intent 分类**: session 存在时跳过首次独立分类，只做一次 `_classify_intent_with_session`
2. **轻量 enrich**: follow-up 消息用 `_enrich_context_followup`，仅在用户明确要求时拉取市场数据
3. **timing 日志**: `[chat_timing]` / `[chat_stream_timing]` 分步记录耗时
4. **intent 继承**: 短消息 (<80字) + general intent → 自动继承 session 主导 intent
