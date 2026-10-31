"""
登录代理 API：cookie 不存在时，把目标站登录页原样转发给前端让用户手动登录

工作方式（经典登录代理）：
- GET  /api/cookie/<website>/login_page 返回包装页：顶栏（完成/取消）+ iframe；
  iframe 内加载 /api/cookie/<website>/proxy/...
- proxy 端点把请求原样转发到 websites.yaml 里该站点域名，返回时：
  * 响应里的 Set-Cookie 不交给浏览器，而是收进后端该站点的 requests.Session
    cookie jar（浏览器看到的全部是同源响应，天然绕开第三方 cookie 限制）；
  * 后续请求自动带上 jar 里的 cookie，登录流程的会话演化和真实浏览器一致；
  * HTML 做同源改写：绝对/协议相对/根相对地址改写到代理路径，并注入 <base>。
- 用户登录完成后点包装页的"完成并保存"，jar 落盘为 datas/cookies/<website>.json，
  之后脚本经 CookieManager 按 website 取用。

局限（诚实声明）：只改写服务端返回的 HTML 文本；登录页若用 JS 拼绝对 URL 跳转、
或依赖严格的 CSP/反代理检测，可能需要针对性处理。404 兜里带了一个 Referer 级
的救援：从代理页发出的根相对请求 404 时自动重定向回代理路径。
"""

import re
from threading import Lock

import requests
from flask import Blueprint, Response, jsonify, request

from src.config.config import config_manager
from src.utils.cookie_manager import CookieManager
from src.utils.logging.logger import SpiderLogger as logger

# 转发给目标站的请求头白名单（Host/Cookie/压缩由代理自管）
_FORWARD_HEADERS = {'accept', 'accept-language', 'content-type', 'user-agent', 'referer'}
# 返回给浏览器的响应头白名单（剥离 CSP/X-Frame-Options/Set-Cookie/编码相关）
_STRIP_HEADERS_PREFIX = ('content-security-policy', 'x-frame-options', 'set-cookie',
                         'content-encoding', 'content-length', 'transfer-encoding',
                         'strict-transport-security', 'content-disposition')

# 登录会话：website -> requests.Session（进程内，save 后销毁）
_SESSIONS: dict = {}
_SESSIONS_LOCK = Lock()


def _site_url(website: str) -> str:
    """从 websites.yaml 取站点入口地址"""
    sites = config_manager.config_dict.get('websites') or {}
    url = str(sites.get(website) or '').strip()
    if not url:
        available = ', '.join(sorted(sites)) or '无'
        raise KeyError(f"websites.yaml 中没有配置 website={website!r} 的入口地址（可用: {available}）")
    return url.rstrip('/')


def _session(website: str) -> requests.Session:
    """取（或创建）该站点的登录会话；已有 cookie 文件时先载入，支持"重登刷新" """
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(website)
        if session is None:
            session = requests.Session()
            if CookieManager.exists(website):
                try:
                    for c in CookieManager.get(website):
                        session.cookies.set(c['name'], c['value'],
                                            domain=c.get('domain'), path=c.get('path') or '/')
                except Exception as e:
                    logger.warning(f"载入 {website} 旧 cookie 失败，将完全重新登录: {e}")
            _SESSIONS[website] = session
        return session


def _rewrite_html(website: str, origin: str, body: bytes) -> bytes:
    """把 HTML 里的目标站地址改写到代理路径，注入 <base> 处理剩余相对路径

    先把绝对/协议相对地址替换为占位符，避免根相对改写把它们再包一层；
    最后统一把占位符还原为代理前缀。
    """
    proxy = f"/api/cookie/{website}/proxy"
    marker = "\x00PROXY\x00"
    html = body.decode('utf-8', errors='replace')
    html = html.replace(origin, marker)                          # https://www.site.com
    html = html.replace('//' + origin.split('//', 1)[1], marker)  # 协议相对 //www.site.com
    # 根相对引用 href="/x"（此时占位符结果不会匹配到这个模式）
    html = re.sub(r'((?:href|src|action|poster|formaction)\s*=\s*["\'])/(?!/)',
                  r'\1' + marker + '/', html, flags=re.I)
    html = html.replace(marker, proxy)
    html = re.sub(r'(<head[^>]*>)', r'\1<base href="' + proxy + r'/">', html, count=1, flags=re.I)
    return html.encode('utf-8')


def _login_page(website: str, origin: str) -> str:
    """包装页：顶栏 + iframe 代理页面"""
    proxy = f"/api/cookie/{website}/proxy/"
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{website} 登录</title>
<style>
  body {{ margin: 0; font: 14px/1.5 -apple-system, "PingFang SC", sans-serif; background: #f5f6f8; }}
  #bar {{ display: flex; align-items: center; gap: 14px; padding: 9px 16px; background: #fff;
         border-bottom: 1px solid #e3e6ea; position: sticky; top: 0; }}
  #bar b {{ font-size: 15px; }}
  #bar .hint {{ color: #6b7280; }}
  #bar .spacer {{ flex: 1; }}
  button {{ padding: 6px 16px; border-radius: 8px; border: 1px solid #e3e6ea; background: #fff; cursor: pointer; }}
  #save {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
  button:disabled {{ opacity: .5; cursor: default; }}
  #msg {{ color: #15803d; }}
  iframe {{ width: 100%; height: calc(100vh - 45px); border: none; display: block; }}
</style>
</head>
<body>
<div id="bar">
  <b>{website} 登录</b>
  <span class="hint">在下方页面完成登录后，点"完成并保存"记录 cookie（目标：{origin}）</span>
  <span class="spacer"></span>
  <span id="msg"></span>
  <button id="save">完成并保存</button>
  <button id="cancel">取消</button>
</div>
<iframe src="{proxy}"></iframe>
<script>
const save = document.getElementById('save');
save.onclick = async () => {{
  save.disabled = true;
  const resp = await fetch('/api/cookie/{website}/save', {{ method: 'POST' }});
  const data = await resp.json().catch(() => ({{ success: false, error: '响应解析失败' }}));
  if (data.success) {{
    document.getElementById('msg').textContent = `已保存 ${{data.cookieCount}} 条 cookie，返回中…`;
    setTimeout(() => location.href = '/', 800);
  }} else {{
    document.getElementById('msg').textContent = data.error || '保存失败';
    save.disabled = false;
  }}
}};
document.getElementById('cancel').onclick = async () => {{
  await fetch('/api/cookie/{website}/cancel', {{ method: 'POST' }});
  location.href = '/';
}};
</script>
</body>
</html>"""


def _err(message, code=400):
    return jsonify({'success': False, 'error': message}), code


class CookieApi:
    """登录 cookie 管理 API 类"""

    def __init__(self):
        self.blueprint = Blueprint('cookie_api', __name__, url_prefix='/api/cookie')
        self._register_routes()

    def _register_routes(self):

        @self.blueprint.route('/status')
        def status():
            """已配置站点与 cookie 存储状态"""
            try:
                sites = config_manager.config_dict.get('websites') or {}
                saved = {r['website']: r for r in CookieManager.status()}
                rows = []
                for website in sorted(set(sites) | set(saved)):
                    info = saved.get(website, {})
                    count = info.get('cookieCount', 0)
                    rows.append({
                        'website': website,
                        'domain': sites.get(website),
                        'hasCookie': count > 0,
                        'cookieCount': count,
                        'updateTime': info.get('updateTime'),
                    })
                return jsonify({'success': True, 'rows': rows})
            except Exception as e:
                logger.error(f"查询 cookie 状态失败: {e}")
                return _err(f"查询 cookie 状态失败: {str(e)}", 500)

        @self.blueprint.route('/<website>/login_page')
        def login_page(website):
            """登录包装页：顶栏 + 代理 iframe"""
            try:
                origin = _site_url(website)
            except KeyError as e:
                return _err(str(e))
            return Response(_login_page(website, origin), content_type='text/html; charset=utf-8')

        @self.blueprint.route('/<website>/proxy', defaults={'path': ''},
                              methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
        @self.blueprint.route('/<website>/proxy/', defaults={'path': ''},
                              methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
        @self.blueprint.route('/<website>/proxy/<path:path>',
                              methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
        def proxy(website, path):
            """把请求转发到目标站：捕获 Set-Cookie，HTML 同源改写"""
            try:
                origin = _site_url(website)
            except KeyError as e:
                return _err(str(e))

            url = f"{origin}/{path}"
            if request.query_string:
                url += '?' + request.query_string.decode('utf-8', errors='replace')

            headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_HEADERS}
            headers.pop('Referer', None)  # referer 指向本代理，原样转发反而暴露代理结构
            try:
                resp = _session(website).request(
                    request.method, url,
                    headers=headers,
                    data=request.get_data() if request.method in ('POST', 'PUT', 'PATCH') else None,
                    timeout=30,
                    allow_redirects=True,
                )
            except requests.RequestException as e:
                logger.error(f"代理请求失败 {website}: {url}: {e}")
                return _err(f"目标站请求失败: {str(e)}", 502)

            content_type = resp.headers.get('Content-Type', '')
            body = resp.content
            if 'text/html' in content_type:
                body = _rewrite_html(website, origin, body)

            out_headers = {'Content-Type': content_type} if content_type else {}
            return Response(body, status=resp.status_code, headers=out_headers)

        @self.blueprint.route('/<website>/save', methods=['POST'])
        def save(website):
            """把该站点登录会话积累的 cookie 落盘"""
            session = _SESSIONS.get(website)
            if session is None or len(session.cookies) == 0:
                return _err('该站点还没有可保存的 cookie，请先在登录页完成登录')
            cookies = [{
                'name': c.name,
                'value': c.value,
                'domain': c.domain,
                'path': c.path,
                'expires': c.expires,
                'secure': bool(c.secure),
            } for c in session.cookies]
            count = CookieManager.save(website, cookies)
            with _SESSIONS_LOCK:
                _SESSIONS.pop(website, None)
            return jsonify({'success': True, 'cookieCount': count})

        @self.blueprint.route('/<website>/cancel', methods=['POST'])
        def cancel(website):
            """放弃本次登录会话"""
            with _SESSIONS_LOCK:
                _SESSIONS.pop(website, None)
            return jsonify({'success': True})

        @self.blueprint.route('/<website>', methods=['DELETE'])
        def delete_cookie(website):
            """删除已保存的 cookie 文件"""
            removed = CookieManager.delete(website)
            return jsonify({'success': True, 'removed': removed})
