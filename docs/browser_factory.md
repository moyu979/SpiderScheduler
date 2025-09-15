# 浏览器工厂 (BrowserFactory) 使用文档

## 概述

`BrowserFactory` 是一个用于创建和配置 Selenium 浏览器实例的工具类。它提供了统一的接口来创建不同类型的浏览器，支持无头模式、代理设置和 Cookie 管理。

## 主要功能

- **多浏览器支持**: 目前支持 Chrome 浏览器
- **无头模式**: 支持无头模式运行，适合服务器环境
- **代理支持**: 可配置 HTTP 代理
- **Cookie 管理**: 自动加载和保存 Cookie
- **反检测**: 内置反自动化检测机制

## 基本使用

### 1. 创建基本浏览器

```python
from src.utils.browser_factory import BrowserFactory

# 创建无头浏览器（默认）
driver = BrowserFactory.create_browser()
driver.get("https://www.example.com")
print(driver.title)
driver.quit()
```

### 2. 创建可见浏览器（用于调试）

```python
# 创建可见浏览器
driver = BrowserFactory.create_browser(headless=False)
driver.get("https://www.example.com")
# 浏览器会显示出来，方便调试
driver.quit()
```

### 3. 使用代理

```python
# 创建带代理的浏览器
driver = BrowserFactory.create_browser(use_proxy=True)
driver.get("https://httpbin.org/ip")
print(driver.page_source)
driver.quit()
```

### 4. 使用 Cookie

```python
# 检查 Cookie 是否存在
if not BrowserFactory.check_cookie_exists():
    # 初始化 Cookie
    BrowserFactory.init_cookies()

# 创建带 Cookie 的浏览器
driver = BrowserFactory.create_browser(use_cookie=True)
driver.get("https://www.example.com")
driver.quit()
```

## 配置项

浏览器工厂使用以下配置项（在 `browser` 配置字典中）：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| BROWSER_TYPE | string | "chrome" | 浏览器类型 |
| BROWSER_PATH | string | "" | 浏览器可执行文件路径 |
| DOMAIN | string | "https://www.example.com" | 目标网站域名 |
| HEADLESS | bool | True | 是否使用无头模式 |
| USE_PROXY | bool | False | 是否使用代理 |
| USE_COOKIE | bool | False | 是否使用cookie |

## Cookie 管理

### 初始化 Cookie

```python
# 初始化 Cookie（如果不存在）
BrowserFactory.init_cookies()

# 指定域名初始化
BrowserFactory.init_cookies("https://www.example.com")
```

### 检查 Cookie 状态

```python
# 检查 Cookie 文件是否存在
if BrowserFactory.check_cookie_exists():
    print("Cookie 文件存在")
else:
    print("Cookie 文件不存在")
```

## 异常处理

### CookieNotExist 异常

当请求使用 Cookie 但 Cookie 文件不存在时抛出：

```python
try:
    driver = BrowserFactory.create_browser(use_cookie=True)
except CookieNotExist as e:
    print(f"Cookie 文件不存在: {e}")
    # 初始化 Cookie
    BrowserFactory.init_cookies()
    driver = BrowserFactory.create_browser(use_cookie=True)
```

## 高级配置

### 自定义浏览器路径

```python
# 在配置中设置浏览器路径
from src.utils.config import set_browser
set_browser('BROWSER_PATH', '/path/to/chrome')
```

### 代理配置

```python
# 在配置中设置代理
from src.utils.config import set_proxy
set_proxy('PROXY_HOST', '127.0.0.1')
set_proxy('PROXY_PORT', '7897')
```

## 最佳实践

### 1. 资源管理

```python
# 使用 with 语句确保浏览器正确关闭
with BrowserFactory.create_browser() as driver:
    driver.get("https://www.example.com")
    # 处理页面
```

### 2. 错误处理

```python
try:
    driver = BrowserFactory.create_browser(use_cookie=True)
    driver.get("https://www.example.com")
    # 处理页面
except CookieNotExist:
    # 处理 Cookie 不存在的情况
    BrowserFactory.init_cookies()
    driver = BrowserFactory.create_browser(use_cookie=True)
except Exception as e:
    print(f"浏览器创建失败: {e}")
finally:
    if 'driver' in locals():
        driver.quit()
```

### 3. 性能优化

```python
# 对于批量操作，复用浏览器实例
driver = BrowserFactory.create_browser()

for url in urls:
    driver.get(url)
    # 处理页面

driver.quit()
```

## 测试

运行测试：

```bash
cd tests
python test_browser_factory.py
```

## 注意事项

1. **Chrome 驱动**: 确保系统中安装了 Chrome 浏览器和对应的 ChromeDriver
2. **代理设置**: 使用代理时需要确保代理服务器可用
3. **Cookie 安全**: Cookie 文件包含敏感信息，请妥善保管
4. **资源清理**: 使用完毕后务必调用 `driver.quit()` 释放资源
5. **无头模式**: 生产环境建议使用无头模式以提高性能

## 示例代码

完整的使用示例请参考 `src/utils/browser_factory_example.py`。
