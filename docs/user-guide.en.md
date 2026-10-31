# SpiderScheduler User Guide

> For operators: installation, a walkthrough of the four tabs, the REST API reference,
> configuration details and troubleshooting. Architecture and development topics live in the
> [Dev Guide](dev-guide.en.md).

## 1. Installation & Running

### 1.1 Local

```bash
pip install -r requirements.txt      # Python 3.10+
python main.py                       # work dir ./docker by default, port 8300
```

Options:

| Option / Env | Description |
|---|---|
| `--basepath <dir>` or `BASEPATH=<dir>` | Work directory (config, database, scripts, downloads all live here) |
| `--repl` | Enter the built-in CLI after startup (`add-pos <authorId> [website]`, `exit`) |

Open `http://127.0.0.1:8300`. The first start generates config templates and an empty
database in the work directory automatically.

> Port note: the default is 8300. Port 5000 is occupied by AirPlay Receiver on macOS, so it
> is avoided; change `rest_api_port` in `confs/network.yaml` if needed.

### 1.2 Docker

```bash
docker compose up -d --build
```

- All data lives in the named volume `spider-data` at `/data` (BASEPATH inside the container);
- `docker stop` triggers a graceful shutdown (waits for in-flight downloads, 1 min grace);
- Edit config at `/data/confs/*.yaml` in the volume (hot-reloaded), or online via the System tab.

### 1.3 Work Directory Layout

```
docker/                          ← BASEPATH
├── confs/*.yaml                 config (online-editable, hot-reloaded)
├── scripts/                     your two user scripts
└── datas/
    ├── spider.db                SQLite database (positions/works/links/schema version)
    ├── cookies/<website>.json   per-site login cookies
    ├── log/                     monthly rotating logs
    ├── download/                final download destination
    └── download_cache/          download cache staging area
```

Backing up = copying this directory; moving hosts = copying this directory.

## 2. The Four Tabs

### 2.1 Works

- **Filters**: site dropdown, multi-state checkboxes (inQueue / downloading / done / failed /
  stopped / unmarked), author (matched via upload links), date range (choose upload-time or
  download-time), keyword (title / work number), sort and pagination. All conditions combine;
  the list auto-refreshes ~0.3 s after any change.
- **Stats strip**: one row per site with per-state counts. Click a site name to filter by it;
  click a state chip to toggle that state in the multi-select.
- **Row actions**: works in `inQueue/downloading/failed` can be **stopped** (state→stopped);
  `stopped/failed/done` works can be **requeued** (state→inQueue).

### 2.2 Positions

- **Add position**: click "Add position", enter the author ID and pick a site (options come
  from `websites.yaml`); it takes effect immediately — the next update round walks that
  author. Duplicates are rejected with a clear message.
- **Filters**: site, state (inQueue/stopped), keyword, add-time range.
- **Row actions**: **Stop tracking** (the author is no longer updated) / **Resume tracking**.
- Each row shows the position's **work count** (established author↔work links).

### 2.3 Cookie

Login credentials per site:

1. On the Cookie tab click **Login** on a site row — a wrapper page opens: a top bar
   (Save & finish / Cancel) plus the **real login page of the target site** (served through a
   same-origin proxy).
2. Log in as usual. Cookies set during the whole flow are captured by the backend, not the
   browser.
3. Click **Save & finish** — cookies are persisted to `datas/cookies/<website>.json` and you
   are returned to the app.
4. Clicking Login again with cookies present = re-login with the old session (useful to
   refresh expired credentials); **Delete** removes the cookie file.

Scripts consume cookies via the injected `cookie_manager` (see §4).

> Limitation: the proxy rewrites HTML returned by the server. Login pages that build absolute
> URLs in JS or enforce strict CSP may need special handling (a Referer-based 404 fallback
> exists).

### 2.4 System

- **User scripts**: shows the current route table (`site → class`, plus the fallback class).
  After editing scripts in the work directory, click **Reload scripts**; broken scripts keep
  the old routes with the reason shown in red.
- **Upload scripts**: two upload rows (download / update script). UTF-8 and syntax validation
  run before saving (syntax errors are rejected and the original file is untouched); the
  dispatcher reloads automatically. Dependencies declared via `# requirements:` are installed
  automatically.
- **Config editor**: pick any section (e.g. `download_setting`, `websites`), edit it as YAML;
  saving writes to disk and takes effect in memory immediately. "Reload all from files"
  forces a full config reload.

## 3. Configuration Reference

Config lives in `confs/*.yaml`; changes hot-reload within ~10 s (System-tab saves apply
immediately). Environment variables override in memory: `<SECTION>_<KEY>` upper-cased, e.g.
`DOWNLOAD_SETTING_DO_DOWNLOAD=true`, `TOKEN_PIXIV=xxx`.

### 3.1 download_setting.yaml (global download config)

| Key | Description | Default |
|---|---|---|
| `do_download` | Download master switch (parent of per-site switches) | false |
| `download_thread` | Default download threads per site (overridable) | 1 |
| `once_download_number` | Per-site per-round download limit, -1 = unlimited | -1 |
| `download_interval` | Per-site round interval in seconds, -1 = keep downloading | -1 |
| `waiting_play` | When true, sleep for the duration returned by the script | false |
| `sleep_second` | Fixed sleep between tasks (seconds) | 10 |
| `use_cache` | Cache switch (see §5) | true |
| `download_path` | Final storage path, supports `${BASE_PATH}` | `./${BASE_PATH}/datas/download` |
| `cache_path` | Cache staging path | `./${BASE_PATH}/datas/download_cache` |

### 3.2 download_sites.yaml (per-site config)

Keys are `website` values; each entry overrides the global settings, missing keys fall back:

```yaml
pixiv:
  download_thread: 2
  sleep_second: 8
  download_interval: 3600
danbooru:
  do_download: false        # disable one site (auto-restarted when re-enabled)
```

Note: `download_thread` is read when a site's scheduler thread starts — restart the process
after changing it; every other key hot-applies.

### 3.3 Other Sections

| Section | Keys |
|---|---|
| `update_setting` | `do_update` master switch, `update_thread`, `update_interval`, `once_update_number`, `commit_interval` (stagger between positions) |
| `websites` | `<website>: entry URL` — target of the login proxy and source of site dropdowns |
| `network` | `rest_api_host` / `rest_api_port`, proxy settings |
| `global_conf` | `conf_reload_interval`, `debug` |
| `database` | `url` (empty = SQLite; a Postgres URL also works), `echo`, `connect_args` |

## 4. User Script Contract

Scripts live in `scripts/` and can be uploaded online (syntax-checked, dependencies
installed).

```python
# requirements: requests>=2.31          ← dependency declaration, auto-installed before load
class DownloadWork:
    website = "pixiv"                   # site served; omit for a single-site fallback file
    # injected: logger / config_manager / cookie_manager

    def __init__(self, work_info, download_path, download_info=None):
        # work_info: {workNumber, website, title, ...}
        # download_path: this task's own directory, already created
        # download_info: downloadInfo deserialized

    def download_it(self):
        ...                             # return the payload path (str) or {path, duration}
```

Update scripts are iterators yielding works (fields in Dev Guide §3.2). If a site is missing
from dropdowns, add its entry URL to `websites.yaml` on the System tab first.

## 5. Download Cache

- `use_cache: true`: the script receives a dedicated cache directory
  `cache_path/<site>_<work>/`; after `download_it()` returns the payload path, the framework
  **copies** it to the final location `download_path/<site>/<work>/` and removes the cache
  directory.
- `use_cache: false`: the script writes the final directory directly, no staging.
- Script code is identical in both modes; toggling the switch requires no script changes.

## 6. REST API Reference

Responses are `{"success": true/false, ...}`; entity identity is always `(id, website)`.

| Endpoint | Description |
|---|---|
| `POST /api/update/add_pos` | `{authorId, website?}` add a publish position (default site pixiv) |
| `POST /api/update/stop_pos` / `resume_pos` | stop / resume tracking a position |
| `POST /api/download/add_work` | `{workNumber, website?, downloadInfo?}` enqueue a work |
| `POST /api/download/stop_work` / `requeue_work` | stop / requeue |
| `GET /api/query/works` | filters: `website` (csv), `state` (csv, `none`=NULL), `author`, `date_field`+`date_from`+`date_to`, `keyword`, `sort`, `order`, `limit`, `offset` |
| `GET /api/query/positions` | filter positions (with `workCount`) |
| `GET /api/query/stats` | site×state counts (powers the stats strip) |
| `GET /api/cookie/status` | per-site cookie status |
| `GET /api/cookie/<w>/login_page` | login wrapper page |
| `POST /api/cookie/<w>/save` / `cancel`, `DELETE /api/cookie/<w>` | save / abandon / delete |
| `GET /api/system/scripts` · `POST .../reload` | route table · hot-reload scripts |
| `GET /api/system/scripts/<kind>/source` · `POST .../upload` | view a script · upload (multipart: `kind`+`file`) |
| `GET /api/system/config` · `GET/PUT /api/system/config/<section>/raw` · `POST /api/system/config/reload` | list sections · read/write YAML · full reload |
| `PUT /api/{update,download,global,network}/config` | update keys of a section (keys must exist) |

## 7. Troubleshooting

- **Page looks stale/blank**: hard-refresh the browser (the HTML is read from disk per request).
- **Config/script change not applying**: config hot-reloads within ~10 s (System-tab saves are
  immediate); scripts need "Reload scripts"; `download_thread` is the exception — restart.
- **Site dropdown empty**: add the site entry to `websites.yaml` on the System tab first.
- **Works stuck at failed**: check the log for the script exception, fix it, then requeue.
- **Login page renders oddly**: strict CSP or JS-built absolute URLs are known proxy
  limitations.
- **Database locked**: WAL + busy_timeout are enabled; avoid opening the same work directory
  from multiple processes.
- **Port 5000 conflicts / AirPlay**: the default is already 8300 — don't switch back on macOS.
