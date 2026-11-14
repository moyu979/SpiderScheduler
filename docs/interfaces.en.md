# SpiderScheduler Interface Reference

> The complete contracts of the two extension points: site **download scripts**
> (`DownloadWork`) and site **update scripts** (`UpdateUser`), plus the public
> interfaces exposed by the `Downloader` / `Updater` scheduler services.
> For site script authors and secondary developers. Operations live in the
> [User Guide](user-guide.en.md); architecture and internals in the
> [Dev Guide](dev-guide.en.md) and [ARCHITECTURE.md](../ARCHITECTURE.md).

## 1. Extension Points at a Glance

| | Download | Update |
|---|---|---|
| Script base class (fallback name) | `DownloadWork` | `UpdateUser` |
| Script directory | `scripts/download/` | `scripts/update/` |
| Per-site config | `site` section of `download.yaml` | `site` section of `update.yaml` |
| Scheduling granularity | per-site scheduler thread + thread pool | same |
| Round pacing | `download_interval` | `update_interval` (round) + `commit_interval` (position stagger) |
| Output | updates `works.state`, writes payload files | inserts `works` rows + `upload` links |

Both script kinds share the same load / route / dependency-install machinery (§2);
the per-kind contracts are §3 and §4; the scheduler services' public methods are §5.

## 2. Conventions Shared by All Scripts

### 2.1 Files and Routing

- **Location**: `scripts/download/`, `scripts/update/` site script directories; one
  file may hold classes for several sites. At deployment the framework installs the
  contract templates as `scripts/download_a_work.py` / `scripts/update_a_user.py`
  (the legacy single-file fallback positions; missing files only, never overwrites).
- **Site declaration**: class attribute `website = "site"` or a list
  `["pixiv", "danbooru"]`; route tables merge across files — the first loaded
  wins on duplicates (with a warning).
- **Fallback**: a file with no class declaring `website` contributes its
  `DownloadWork` / `UpdateUser` class as a legacy single-file fallback for any
  unrouted site.
- **Dependencies**: declare `# requirements: pkg[version]` in the script header
  (multiple lines / comma separated); the framework pip-installs missing ones
  before loading.
- **When changes take effect**: every upload/delete/reload rescans; new files
  take effect immediately; a failed scan keeps the old routes. After a download
  script upload/reload succeeds, suspended `noDownloader` works are requeued
  automatically (see §3.4).

### 2.2 Injected Attributes

Assigned by the framework **after** construction (do **not** read them in
`__init__`):

| Attribute | Value | Purpose |
|---|---|---|
| `logger` | `SpiderLogger` class | unified logging, attributed to the script class |
| `config_manager` | global `ConfigManager` singleton | config access (with `${BASE_PATH}` and env overrides) |
| `cookie_manager` | `CookieManager` class | per-website login cookie storage |
| `tools` | `ScriptTools` instance | runtime toolkit bound to the task's site |

`ScriptTools` (`src/service/script_tools.py`) public methods:

| Method | Purpose |
|---|---|
| `log(level, message)` | log with site context (`"info"` / `"warning"` / …) |
| `site_origin()` | the site's entry URL from websites.yaml (`ScriptToolsError` if unconfigured) |
| `proxy_url()` | proxy address from system.yaml; `None` when disabled |
| `get_proxies()` | proxy dict for requests; `{}` when disabled |
| `get_driver(...)` | Chrome (Selenium) with the site's login cookies and proxy; call `driver.quit()` when done; needs `# requirements: selenium` |
| `register(name, fn)` | register an extension tool, callable as `self.tools.<name>(...)` |

`CookieManager` (`src/utils/cookie_manager.py`) public interface:
`exists(website)` / `get(website)` (for Selenium `add_cookie`) /
`get_header(website)` (requests `Cookie` header) / `save(website, cookies)` /
`delete(website)` / `status()` (overview of all cookies, for the Cookie tab).
`cookie_file(website)` exposes the raw storage path (Selenium JSON). For CLI
tools that only read Netscape `cookies.txt` (you-get, yt-dlp, …),
`netscape_file(website)` returns a framework-managed export at
`BASEPATH/datas/cookies/netscape/<website>.txt` — generated on demand and
refreshed automatically whenever the source JSON changes; pass the path
straight to `--cookies`, no temp-file handling needed.
`netscape_lines(cookies)` converts any Selenium-format cookie list to Netscape
text lines (for temp-file export of memory-passed cookies). JSON files live at
`BASEPATH/datas/cookies/<website>.json`, written by the login proxy.

### 2.3 Templates and Examples

- Contract templates (deployment skeletons with full contract docs):
  `src/assets/scripts/download_a_work.py`, `src/assets/scripts/update_a_user.py`.
- Runnable examples (local fake site): `demos/demo_site_downloader.py`,
  `demos/demo_site_updater.py` (`demos/run_demo.py` boots the whole chain).

## 3. DownloadWork Contract (Download Scripts)

### 3.1 Required Interface

```python
class XXXWork(DownloadWork):
    website = "site"            # or a list; undeclared = this file is the fallback

    def __init__(self, work_info: dict, download_path: str, download_info: dict | None):
        ...

    def download_it(self) -> str | dict:
        ...  # perform the download and return the payload path; raising = task failed
```

### 3.2 Constructor Arguments

**`work_info`** — work snapshot dict:

| Key | Meaning |
|---|---|
| `workNumber` | work id (unique within the site) |
| `website` | site name |
| `upTime` / `title` / `kind` | source-site metadata (from the updater or `add_work`) |
| `state` / `downloadDate` / `downloadPriority` | download-pipeline fields |
| `downloadInfo` | the work's unified download parameters (see §3.3) |

**`download_path`** — the site-level download root `<root>/<website>/`:
points into the cache root when `use_cache` is on, otherwise the final save root
(the cache toggle is transparent to scripts). **The script builds its own
per-work subdirectory** (recommended: the base class helper
`self._work_subdir(work_number)`, which sanitizes unsafe filename characters)
and writes payloads there.

**`download_info`** — the deserialized `work_info["downloadInfo"]` (JSON text),
or `None`. The framework pre-fills `{"authorId", "workNumber"}` (written by the
updater); the `add_work` API accepts a JSON object directly. By convention a
`"cookies"` key carries task-level cookies (in-memory injection, same shapes as
§4.2) — only relevant when instantiating the script directly as a library.

### 3.3 Return Value and Delivery Rules

`download_it()` returns:

- `str`: the payload path — relative to `download_path` (the site download
  root) or absolute;
- `dict`: `{"path": payload path, "duration": seconds}`, `duration` used by
  `waiting_play` to simulate playback time.

Delivery rules (cache mode, handled by the framework):

- cache root ≠ final save root: the framework **moves** the payload to
  `download_path/<website>/` by relative layout and cleans the work's leftovers
  on the cache side;
- the two roots are equal (no staging layer) or `use_cache` is off: payloads
  stay where the script wrote them;
- cache mode with an empty path, the site root itself, or a path outside the
  cache root → the task fails.

### 3.4 Failure and Suspension Semantics

| Situation | Result |
|---|---|
| `download_it()` raises anything | work → `failed`, exception logged |
| no script routed for the site (`ScriptRouteError`) | work → `noDownloader` suspended (**not** `failed`) |
| API sets `stopped` during download/suspension | stays `stopped`; completion callbacks never overwrite it |

Suspended works are not claimed. When the site's script is uploaded/reloaded or
the service starts, sites that now have a usable script get their suspended
works requeued automatically (`Downloader.requeue_no_downloader()`).

### 3.5 Per-Site Config Keys (`site` section of download.yaml)

Resolution order `site.<website> > site.default > built-in fallback`; all keys
hot-reload.

| Key | Default | Meaning |
|---|---|---|
| `do_download` | `true` | site-level download toggle (root `do_download` is the master switch) |
| `download_thread` | `1` | download threads per site (change requires restart) |
| `download_interval` | `3600` | seconds between rounds; `-1` = keep downloading |
| `once_download_number` | `-1` | per-round download cap; `-1` = unlimited |
| `use_cache` | `true` | payloads go to cache first, then are moved to the final save root |
| `download_path` | `datas/download` | final save root (`${BASE_PATH}` supported) |
| `cache_path` | `datas/download_cache` | cache staging root |
| `sleep_second` | `15` | fixed pause between tasks (seconds) |
| `waiting_play` | `false` | pause for the script-returned `duration` (video sites) |
| `download_window` | none | download window: `mode: daily/weekly/monthly`, `start/end: "HH:MM"` (overnight ok), `weekdays: [1-7]`, `month_days` (negative = from month end); unset = always allowed |

Root keys: `do_download` (master switch), `site_scan_interval` (supervisor
tick), `window_check_interval` (out-of-window poll tick).

## 4. UpdateUser Contract (Update Scripts)

### 4.1 Required Interface (choose one of two modes)

```python
class XXXUpdate(UpdateUser):
    website = "site"            # or a list; undeclared = this file is the fallback

    def __init__(self, usr: dict, logging):
        ...                     # usr is the position snapshot; just store it
```

- **Template mode**: implement `get_one_page()` — fetch one page into
  `self.works`; the base class provides the default `__iter__/__next__`;
- **Generator mode** (recommended for browser flows): implement `__iter__`
  returning a generator — incremental sync breaks out early, and the
  generator's `finally` releases browsers and other resources promptly without
  relying on GC.

### 4.2 Constructor Arguments

**`usr`** — position snapshot dict: `authorId` / `website` / `addTime` (the only
framework fields). When instantiating directly as a library, a `usr["cookies"]`
key may carry cookies (Selenium `list[dict]`, `{name: value}` dict, or
`"k=v; k=v"` string; not a framework field).

**`logging`** — the framework logger object (`SpiderLogger`), used like
`logger.info(...)`.

**Injected attributes**: `cookie_manager` (CookieManager class), `tools`
(ScriptTools), `page_interval` (seconds between pages, parsed from
`site.<website>.page_interval`; paging is script-controlled — sleep this value
between fetches; pure-API sites may ignore it).

### 4.3 Yielded Items (dicts from the iterator)

| Key | Required | Meaning |
|---|---|---|
| `workid` or `workNumber` | ✔ | work id (unique within the site) |
| `upTime` | | upload time |
| `title` / `kind` | | source-site metadata |
| `state` | | the source site's own state → stored in `otherInfo.siteState` (never the pipeline state) |
| `downloadDate` / `downloadPriority` | | download-pipeline fields (optional) |
| `downloadInfo` | | per-work download params (optional dict): merged with the preset `{"authorId", "workNumber"}` then stored as JSON; yielded keys win on conflict |

**Yield from newest to oldest** — incremental sync depends on the order.

### 4.4 Incremental Sync and Persistence (framework side)

- Each yielded item first checks the `upload` link: if it **already exists the
  position is considered synced up to here and the framework stops iterating
  this position** (the script does not need to dedupe);
- new works are inserted into `works` (existing ones skipped; races fall back
  to IntegrityError handling), `state` is always `inQueue`, and `downloadInfo`
  is the preset `{"authorId", "workNumber"}` merged with the yielded
  `downloadInfo` (if any); non-dict or unserializable values are logged and
  fall back to the preset;
- the `upload` link is created (existing ones skipped).

### 4.5 Per-Site Config Keys (`site` section of update.yaml)

| Key | Default | Meaning |
|---|---|---|
| `do_update` | `true` | site-level update toggle (root `do_update` is the master switch) |
| `update_thread` | `1` | update threads per site (change requires restart) |
| `update_interval` | `21600` | seconds between rounds (±10% jitter); `-1` = keep updating |
| `commit_interval` | `8` | seconds between submitting successive positions (stagger) |
| `page_interval` | `5` | seconds between pages within one position, fed to the script |

## 5. Scheduler Service Interfaces

### 5.1 Downloader (`src/service/downloader.py`, module singleton `downloader`)

`works.state` machine:
`inQueue (or NULL, legacy data) → downloading → done / failed`;
`stopped` may be set via API at any time (skipped by scheduling, never
overwritten by completion callbacks); `noDownloader` suspension see §3.4;
`downloading` leftovers from a crashed process are reset to `inQueue` at each
round start.

| Method | Purpose |
|---|---|
| `init()` | build the script dispatcher + requeue suspended works + start the supervisor thread |
| `stop()` | set the stop event (all sleeps wake immediately) + shut down each site's pool |
| `site_setting(website, key, default)` | per-site config lookup (the §3.5 chain) |
| `requeue_no_downloader()` | requeue suspended works whose site now has a script; returns the count; called automatically from `init()` and after script upload/reload |

### 5.2 Updater (`src/service/updater.py`, module singleton `updater`)

| Method | Purpose |
|---|---|
| `init()` | build the script dispatcher (threads start via `start()`) |
| `start()` | start the supervisor thread |
| `stop()` | set the stop event + shut down site pools and the "update-now" executor |
| `site_setting(website, key, default)` | per-site config lookup (the §4.5 chain) |
| `update_position_now(website, author_id)` | update one position immediately (background, bypassing rounds; returns `{"started": bool}`) |
| `manual_status()` | snapshot of "update-now" states (key `"website|authorId"`, for frontend polling) |

### 5.3 ScriptDispatcher (`src/service/dispatcher.py`)

| Method | Purpose |
|---|---|
| `load()` | re-evaluate script sources and load them, merging routes across files; failures keep old routes |
| `get(website)` | exact match → fallback class; raises `ScriptRouteError` (lists available sites) |
| `snapshot()` | route-table snapshot (website → class name + fallback), shown on the system page |
| `sites_by_file()` | sites declared per file (for upload conflict detection) |
| `websites()` / `has_fallback()` | registered sites / whether a fallback exists (lets the download side know a script is in place) |
