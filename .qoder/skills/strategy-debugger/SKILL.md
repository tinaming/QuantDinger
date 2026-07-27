---
name: strategy-debugger
description: >-
  诊断 ChanQuant IndicatorStrategy 和 ScriptStrategy 的常见问题：
  信号不准、回测异常、未来函数、参数失效等。
  Trigger: '策略不准', '信号异常', '回测失败', 'strategy debug', 'future leak',
  '未来函数', 'look-ahead', '信号不触发', '回测结果异常'
---

# 策略调试助手 (Strategy Debugger)

## 适用场景

当策略出现以下问题时使用：
- 回测收益异常高/异常低
- 买卖信号不符合预期
- 信号不触发或过于频繁
- 实盘和回测表现不一致
- 怀疑存在未来函数（look-ahead bias）

## 诊断流程

### Step 1: 收集问题信息

询问/检查：
1. 策略代码（Indicator IDE 中的完整代码）
2. 使用的标的和时间周期
3. 参数值
4. 具体的异常表现（截图最好）

### Step 2: 检查常见陷阱

#### 陷阱 1: 未来函数（Look-Ahead Bias）

```python
# 错误 —— 用了当前 bar 的 close 来决定当前 bar 的信号
df['buy'] = df['close'] > df['sma_20']  # 信号在 bar 收盘前就触发了！

# 正确 —— 用上一根 bar 的数据
df['buy'] = df['close'].shift(1) > df['sma_20'].shift(1)
```

**快速检查方法**：
- 搜索代码中是否有 `.shift(-1)` 或负数索引
- 检查是否用了未 shift 的当前 bar 数据
- 检查是否有 `df.iloc[-1]` 这种取最后一行的操作

#### 陷阱 2: 持续触发 vs 边缘触发

```python
# 错误 —— 条件成立的每根 bar 都触发（持续触发）
df['buy'] = df['rsi'] < 30  # RSI < 30 可能连续多根 bar

# 正确 —— 条件刚成立时触发一次（边缘触发）
df['buy'] = (df['rsi'].shift(1) >= 30) & (df['rsi'] < 30)
```

**快速检查方法**：
- 看 buy/sell 列的 True 密度，如果 >30% 的 bar 都是 True → 可能是持续触发
- 用 `df['buy'].sum() / len(df)` 计算信号密度

#### 陷阱 3: NaN 处理不当

```python
# 错误 —— SMA 前 N 行是 NaN，比较时产生 False negative
df['buy'] = df['close'] > df['sma_200']  # 前 200 行全是 NaN

# 正确 —— 先 fillna 再比较，或确保 dropna
df['buy'] = (df['close'] > df['sma_200']) & df['sma_200'].notna()
```

#### 陷阱 4: 参数边界问题

```python
# @param fast_period (int, 1, 200, 5)
# @param slow_period (int, 1, 200, 20)

# 问题：fast_period 可能 >= slow_period
# 需要在代码中防护
if fast_period >= slow_period:
    fast_period, slow_period = slow_period, fast_period
```

### Step 3: 验证数据质量

```python
# 在策略代码开头添加数据检查
print(f"数据范围: {df.index[0]} ~ {df.index[-1]}")
print(f"数据行数: {len(df)}")
print(f"缺失值: {df.isna().sum().sum()}")
print(f"零值行数: {(df['close'] == 0).sum()}")
print(f"时间间隔: {df.index.to_series().diff().mode().values[0]}")
```

### Step 4: 对比回测 vs 信号

用平台的回测功能，对比：
1. **信号数量** — 买入 N 次，卖出 M 次是否合理
2. **胜率** — >70% 可能过拟合，<30% 可能信号有反转
3. **最大回撤** — >50% 说明风控缺失
4. **交易频率** — 太低可能是数据问题，太高可能是持续触发

### Step 5: 给出修复建议

根据诊断结果，修改策略代码。常见修复模式：

| 问题 | 修复方向 |
|------|---------|
| 信号过多 | 添加边缘触发 + 信号冷却期 |
| 信号过少 | 检查 NaN、参数范围、数据质量 |
| 收益虚高 | 检查未来函数，添加 `.shift(1)` |
| 实盘偏差 | 检查滑点设置、手续费、流动性 |

## 关键文件

| 文件 | 用途 |
|------|------|
| `docs/STRATEGY_DEV_GUIDE_CN.md` | 完整策略开发指南 |
| `docs/SIGNAL_EXECUTION_STANDARD_CN.md` | 信号执行标准 |
| `docs/examples/dual_ma_with_params.py` | 双均线范例 |
| `docs/examples/` | 4 个完整策略模板 |
| `app/services/backtest.py` | 回测引擎逻辑 |
| `app/utils/safe_exec.py` | 策略沙盒执行 |

## 信号标准速查

```python
# IndicatorStrategy 标准输出
# buy: True = 做多信号（刚触发）
# sell: True = 做空/平仓信号（刚触发）
# exit_owner: "indicator" 表示策略自己管理退出
# exit_owner: "engine" 表示引擎管理止盈止损

# @param 参数名 (类型, 最小值, 最大值, 默认值)
# @strategy stop_loss=0.03 take_profit=0.06 position_size=0.1
```

## 注意事项

- 回测引擎使用 **下一根 bar 的 open** 作为默认成交价（`signalTiming: next_bar_open`）
- 策略代码运行在沙盒中，`import` 受限，只允许标准库 + pandas + numpy
- 不要在策略代码中打印过多内容，会拖慢回测速度
- 如果发现未来函数，**必须**明确告知用户并标注问题行号
