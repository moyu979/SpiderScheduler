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
> is avoided; change `rest_api_port` in `confs/system.yaml` if needed.

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
  stopped / noDownloader / unmarked), author (matched via upload links), date range (choose upload-time or
  download-time), keyword (title / work number), sort and pagination. All conditions combine;
  the list auto-refreshes ~0.3 s after any change.
- **Stats strip**: one row per site with per-state counts. Click a site name to filter by it;
  click a state chip to toggle that state in the multi-select.
- **Row actions**: works in `inQueue/downloading/failed/noDownloader` can be **stopped** (state→stopped);
  `stopped/failed/done` works can be **requeued** (state→inQueue).
  `noDownloader` is a suspended state: works whose site has no download script yet are not
  marked failed — once you upload a download script for that site they are requeued automatically.

### 2.2 Positions

- **Add position**: click "Add position", enter the author ID and pick a site (options come
  from `websites.yaml`); it takes effect immediately — the next update round walks that
  author. Duplicates are rejected with a clear message.
- **Filters**: site, state (inQueue/stopped), keyword, add-time range.
- **Row actions**: **Stop tracking** (the author is no longer updated) / **Resume tracking**;
  **Update now** (bypasses the round schedule and syncs this one position in the
  background — the button turns into "updating…" and shows the added count when done).
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
- **Upload scripts**: pick a kind (download / update) and a .py file; the "file name" field is the server-side save name — leave it empty to derive it from the uploaded file's name (non-ASCII names need a manual save name). Scripts use
  **multi-file dispatch**: `scripts/<kind>/<name>.py`, one file per site, routes merged across
  files. UTF-8/syntax validation runs first, then two conflict checks — a file with the same
  name, or a website already declared by another script — return 409 and **the UI asks whether
  to overwrite** (confirmed with force); **after a successful save the dispatcher is rescanned
  immediately**, so new files take effect at once; on rescan failure old routes stay active.
  The file list supports viewing and deleting online (delete rescans too).
- **Config editor**: pick any section (e.g. `download`, `websites`), edit it as YAML;
  saving writes to disk and takes effect in memory immediately. "Reload all from files"
  forces a full config reload.

## 3. Configuration Reference

Config lives in `confs/*.yaml`; changes hot-reload within ~10 s (System-tab saves apply
immediately). Environment variables override in memory: `<SECTION>_<KEY>` upper-cased, e.g.
`DOWNLOAD_DO_DOWNLOAD=true`, `WEBSITES_PIXIV=https://www.pixiv.net`.

### 3.1 download.yaml (download config: global + site layers merged)

Root keys are the switches and scan periods that **cannot be overridden per
site**; all site-overridable keys live under the `site` structure (resolution
order: **site.<website> > site.default > built-in code defaults** — a missing
key on any layer never breaks scheduling). Day-to-day tuning only touches
`site.default`:

```yaml
# ---- global layer (root keys) ----
do_download: false            # download master switch (parent of per-site switches)
site_scan_interval: 5         # site-scan period in seconds (discovery delay)
window_check_interval: 60     # poll period outside the download window

# ---- site layer ----
site:
  default:                    # shared defaults for all sites
    download_thread: 1        # download threads per site
    once_download_number: -1  # per-round download limit, -1 = unlimited
    download_interval: 3600   # round interval in seconds, -1 = keep downloading
    waiting_play: false       # sleep for the duration returned by the script
    sleep_second: 15          # fixed sleep between tasks (seconds)
    use_cache: true           # cache switch (see §5)
    download_path: "./${BASE_PATH}/datas/download"
    cache_path: "./${BASE_PATH}/datas/download_cache"

  pixiv:                      # a site section only lists keys that differ
    download_thread: 2
    sleep_second: 8
  danbooru:
    do_download: false        # disable one site (auto-restarted when re-enabled)
```

Note: `download_thread` is read when a site's scheduler thread starts — restart the process
after changing it; every other key hot-applies. Without `download_path`/`cache_path` the
code falls back to `BASEPATH/datas/{download,download_cache}`.

### 3.1.1 Download Window (burst-burn proxy traffic)

Each site can define *when* downloading is allowed — outside the window the site's scheduler
thread idles quietly (re-evaluated every 60 s) and starts grabbing the moment the window
opens. Three modes (`start`/`end` are HH:MM, overnight ranges like 22:00-06:00 are supported):

| mode | Meaning | Extra keys |
|---|---|---|
| `daily` | same time range every day | — |
| `weekly` | range on chosen weekdays | `weekdays: [1, 5]` (1=Mon…7=Sun) |
| `monthly` | range on chosen days of month | `month_days: [1, 2, -1]` (negatives count from month end, -1=last day) |

Recommended recipe for burning proxy traffic (full speed inside the window):

```yaml
# download.yaml
site:
  pixiv:
    download_window:
      mode: monthly          # the 1st, 2nd and last day of each month
      month_days: [1, 2, -1]
    once_download_number: -1   # unlimited
    download_interval: -1      # continuous
    sleep_second: 0            # no pause between tasks
```

Details: no new tasks are claimed outside the window; in-flight tasks finish naturally. No
window configured = unrestricted. Invalid config (bad time format, weekly without weekdays,
monthly without month_days) **fails open** with a warning — it never silently stops your
downloads.

### 3.2 update.yaml (update config: global + site layers merged)

Same structure as download.yaml: root key `do_update` master switch;
`site.default` holds `update_thread` (threads) / `update_interval` (round
interval) / `commit_interval` (submit stagger **between positions**) /
`page_interval` (fetch interval **between pages within one position**, resolved
by the framework and injected into the updater script — pagination is owned by
the script; pure-API sites can ignore it); `site.<website>` overrides per site
(updates crawl the target site too — rate-limit per site).

### 3.3 Other Sections

| Section | Keys |
|---|---|
| `system` | merged from four files: `debug`/`conf_reload_interval`/`conf_retry_interval` (runtime), `console_log_level`/`file_log_level` (logging), `database_url`/`database_echo`/`database_connect_args` (database; remote DBs skip schema migration), `rest_api_host`/`rest_api_port`/`use_proxy`/`proxy_ip`/`proxy_port` (network & proxy) |
| `websites` | `<website>: entry URL` — target of the login proxy and source of site dropdowns; manageable online on the Cookie tab (writes back to this file) |

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
        # download_path: site-level download root <root>/<site>/; the script
        #                builds its own per-work subdirectory under it
        # download_info: downloadInfo deserialized

    def download_it(self):
        ...                             # return the payload path (str) or {path, duration}
```

Update scripts are iterators yielding works (fields in Interface Reference §4.3). If a site is missing
from dropdowns, add it via "Add site" on the Cookie tab first (writes back to `websites.yaml`).

## 5. Download Cache

- `use_cache: true`: the script receives the site-level download root
  `cache_path/<site>/` and builds its own per-work subdirectory; after `download_it()`
  returns the payload path (relative to that root or absolute), the framework **moves** it
  to the final location `download_path/<site>/` by relative layout and cleans the work's
  leftovers on the cache side.
- `use_cache: false`, or `cache_path` equal to `download_path`: treated as no staging
  layer — payloads stay where the script wrote them, nothing is moved.
- Script code is identical in both modes; toggling the switch requires no script changes.

## 6. REST API Reference

Responses are `{"success": true/false, ...}`; entity identity is always `(id, website)`.

| Endpoint | Description |
|---|---|
| `POST /api/update/add_pos` | `{authorId, website?}` add a publish position (default site pixiv) |
| `POST /api/update/stop_pos` / `resume_pos` | stop / resume tracking a position |
| `POST /api/update/update_now` | `{authorId, website?}` update one position immediately (background); `GET /api/update/update_now/status` for status |
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
- **Site dropdown empty**: add the site via "Add site" on the Cookie tab first (writes back
  to `websites.yaml`).
- **Works stuck at failed**: check the log for the script exception, fix it, then requeue.
- **Works shown as "noDownloader"**: the site has no download script yet — upload one for that
  site on the System tab and the works are requeued automatically (or click "Reload scripts").
- **Login page renders oddly**: strict CSP or JS-built absolute URLs are known proxy
  limitations.
- **Database locked**: WAL + busy_timeout are enabled; avoid opening the same work directory
  from multiple processes.
- **Port 5000 conflicts / AirPlay**: the default is already 8300 — don't switch back on macOS.
