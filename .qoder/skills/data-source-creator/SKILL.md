---
name: data-source-creator
description: >-
  为 ChanQuant 创建新的行情数据源适配器。遵循工厂模式，继承 BaseDataSource，
  实现 K 线和报价接口。
  Trigger: '新数据源', '接入行情', 'add data source', 'data adapter',
  '数据适配器', '行情接口', '接入新交易所'
---

# 新建数据源适配器 (Data Source Creator)

## 适用场景

当需要接入新的行情数据提供商（如新的交易所、行情 API）时使用。

## 架构

```
app/data_sources/
├── base.py          ← BaseDataSource（必须继承）
├── factory.py       ← DataSourceFactory（必须注册）
├── errors.py        ← 自定义异常
├── crypto.py        ← 加密货币数据源（参考范例）
├── cn_stock.py      ← A 股数据源（参考范例）
└── ...
```

## 执行步骤

### Step 1: 读取参考文件

1. 读取 `app/data_sources/base.py` — 理解 `BaseDataSource` 接口
2. 读取 `app/data_sources/factory.py` — 理解注册机制
3. 读取一个现有适配器（如 `app/data_sources/crypto.py`）作为模板

### Step 2: 创建数据源文件

```python
# app/data_sources/my_new_source.py

from typing import Dict, List, Any, Optional
from app.data_sources.base import BaseDataSource
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MyNewSourceDataSource(BaseDataSource):
    """接入 XXX 行情 API"""

    name = "my_new_source"

    def __init__(self):
        # 初始化 API client，读取环境变量中的 API Key
        self.api_key = os.getenv("MY_NEW_SOURCE_API_KEY", "")
        self.base_url = os.getenv("MY_NEW_SOURCE_BASE_URL", "https://api.xxx.com")

    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取 K 线数据。
        必须返回标准格式：
        [{"time": int, "open": float, "high": float, "low": float, "close": float, "volume": float}, ...]
        """
        # 1. 调用 API 获取原始数据
        # 2. 转换为标准格式（用 self.format_kline()）
        # 3. 用 self.filter_and_limit() 处理分页和时间过滤
        # 4. 用 self.log_result() 记录数据质量
        klines = []
        # ... 实现逻辑 ...
        self.log_result(symbol, klines, timeframe)
        return klines
```

### Step 3: 在工厂中注册

在 `factory.py` 中添加：

```python
# 在 _MARKET_ALIASES 中添加别名
_MARKET_ALIASES["mynewsource"] = "MyNewSource"

# 在 DataSourceFactory 的 _get_source() 中添加实例化
if market_key == "MyNewSource":
    from app.data_sources.my_new_source import MyNewSourceDataSource
    source = MyNewSourceDataSource()
```

### Step 4: 添加环境变量

在 `env.example` 中添加：

```bash
# MyNewSource 数据源
MY_NEW_SOURCE_API_KEY=
MY_NEW_SOURCE_BASE_URL=https://api.xxx.com
```

### Step 5: 编写测试

```python
# tests/test_my_new_source.py

from unittest.mock import patch, MagicMock
from app.data_sources.my_new_source import MyNewSourceDataSource


@patch('app.data_sources.my_new_source.requests.get')
def test_get_kline_returns_normalized_data(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: [...]  # 模拟 API 响应
    )
    source = MyNewSourceDataSource()
    klines = source.get_kline("BTC/USDT", "1H", 10)
    assert len(klines) > 0
    assert "time" in klines[0]
    assert "open" in klines[0]
```

## K 线标准格式（必须遵守）

```python
{
    "time": 1700000000,     # Unix 时间戳（秒），UTC
    "open": 43250.5,        # 开盘价（float）
    "high": 43300.0,        # 最高价（float）
    "low": 43200.0,         # 最低价（float）
    "close": 43280.0,       # 收盘价（float）
    "volume": 125.67        # 成交量（float，以标的资产为单位）
}
```

## 关键文件

| 文件 | 用途 |
|------|------|
| `app/data_sources/base.py` | BaseDataSource 接口定义 |
| `app/data_sources/factory.py` | 工厂注册 + 别名映射 |
| `app/data_sources/crypto.py` | 加密货币数据源（最佳参考） |
| `env.example` | 环境变量模板 |

## 注意事项

- **必须**使用 `self.format_kline()` 标准化输出，不要自己拼装 dict
- **必须**使用 `self.filter_and_limit()` 处理分页，不要自己写排序/截断
- **不要**在 `__init__` 中发起网络请求，延迟到 `get_kline()` 调用时
- **不要**假设 API 返回的时间戳格式，务必确认是秒还是毫秒
- 如果 API 有限流，使用 `time.sleep()` 或添加指数退避重试
- 网络请求超时设置为 10 秒，异常时返回空列表而非抛异常（容错优先）
