---
name: test-writer
description: >-
  为 ChanQuant 后端自动生成符合项目规范的 pytest 测试代码。
  Trigger: '写测试', '补测试', 'write test', 'add test', 'test coverage',
  '测试覆盖率', 'pytest', '单元测试'
---

# 自动写测试 (Test Writer)

## 适用场景

当需要为以下目标补充测试时使用：
- `app/services/` 下的业务逻辑函数
- `app/routes/` 下的 API 端点
- `app/utils/` 下的工具函数
- `app/data_sources/` 下的数据源适配器

## 执行步骤

### Step 1: 分析目标代码

先读取目标文件，理解：
1. 函数签名和参数类型
2. 返回值结构
3. 边界条件（空输入、None、异常路径）
4. 依赖的外部服务（DB、Redis、HTTP 等）

### Step 2: 确定测试类型

| 目标位置 | 测试类型 | fixture 需求 |
|---------|---------|-------------|
| `services/` 纯函数 | 单元测试 | 无 |
| `services/` 依赖 DB | 集成测试 | `app` fixture |
| `routes/` API | 端点测试 | `client` fixture |
| `data_sources/` | Mock 测试 | `unittest.mock` |

### Step 3: 编写测试代码

**必须遵循的规范**：

```python
# 文件位置：backend_api_python/tests/test_xxx.py
# 命名规则：test_{功能描述}.py
# 函数命名：test_{被测函数}_{场景描述}

# 示例：
def test_parse_strict_mode_defaults_true():
    """验证 parse_strict_mode 默认返回 True"""
    assert parse_strict_mode(None) is True

def test_parse_strict_mode_zero_returns_false():
    """验证 '0' 字符串返回 False"""
    assert parse_strict_mode('0') is False
```

### Step 4: 处理外部依赖

**DB 依赖** — 使用 `app` fixture 自动注入：

```python
def test_something_with_db(app):
    with app.app_context():
        result = some_service.do_something()
        assert result is not None
```

**HTTP/API 依赖** — 使用 `unittest.mock.patch`：

```python
from unittest.mock import patch, MagicMock

@patch('app.services.xxx.requests.get')
def test_fetch_with_mock_http(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"data": [...]}
    )
    result = some_service.fetch_data()
    assert len(result) > 0
```

**Exchange 依赖** — 使用 CCXT Mock：

```python
@patch('app.services.exchange_execution.ccxt.binance')
def test_order_placement(mock_exchange_cls):
    mock_exchange = MagicMock()
    mock_exchange.create_order.return_value = {"id": "123", "status": "open"}
    mock_exchange_cls.return_value = mock_exchange
    # ... test logic
```

### Step 5: 验证

```powershell
# 运行刚写的测试
cd d:\aaron\miniso\ChanQuant\backend_api_python
pytest tests/test_xxx.py -v
```

## 关键文件

| 文件 | 用途 |
|------|------|
| `tests/conftest.py` | 全局 fixture（app、client） |
| `tests/test_backtest_execution.py` | 纯函数测试范例 |
| `tests/test_agent_v1.py` | API 端点测试范例 |
| `pytest.ini` | pytest 配置 |

## 注意事项

- **不要**在测试中发起真实 HTTP 请求或连接真实交易所
- **不要**依赖 `backend_api_python/.env` 的实际值，`conftest.py` 已设置最小环境
- **不要**测试需要真实 API Key 的功能，除非标注 `@pytest.mark.integration`
- 每个测试函数应该是独立的，不依赖其他测试的执行顺序
- 边界条件至少覆盖：None、空列表/字典、极值、正常值
