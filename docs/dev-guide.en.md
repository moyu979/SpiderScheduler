# SpiderScheduler Dev Guide

> For contributors: architecture layers, the script plugin lifecycle, state machines, database
> and migrations, scheduler internals, the config system, frontend structure, testing and the
> extension guide. Operations live in the [User Guide](user-guide.en.md); the architecture
> document kept in sync with the code is [ARCHITECTURE.md](../ARCHITECTURE.md).

## 1. Architecture Overview

```
main.py ──► src/core/initialization.py (single init: files→config→logging→db→API→Updater→Downloader)
                     │
     ┌───────────────┼────────────────┬─────────────────┐
     ▼               ▼                ▼                 ▼
 src/config     src/server       src/service        src/utils
 config/paths   rest_api + 7     updater/downloader  database/cookie/logging/
 (hot reload)   blueprints + web dispatcher          threadPool/dynamic_loader
```

Dependencies point downwards only; no reverse imports. ~5400 lines of Python plus a 958-line
single-file frontend.

Key decisions and their rationale:

- **Site differences live in data**: `downloadInfo` carries per-work parameters,
  `download.yaml` (site section) carries pacing, `websites.yaml` carries entry URLs; the framework has
  zero site logic.
- **Scripts are plugins**: dynamic loading + routing by `website`; dependencies auto-installed
  before load; failed reloads keep old routes.
- **Single-writer model**: claiming and state writes happen only in each site's scheduler
  thread — race-free by construction. SQLite runs WAL + busy_timeout + enforced foreign keys.

## 2. Data Model

All three tables are keyed by `website` (migration history: v1 multiWeb initial schema;
v2 renamed user→publish_pos).

```
publish_pos (publish position)  works                          upload
  authorId ─┐(PK)               workNumber ─┐(PK)              website  (PK)
  website ──┘(PK)              website ────┘(PK)              authorId (PK, FK→publish_pos)
  addTime                      upTime/title/kind              workNumber(PK, FK→works)
  state                        state / downloadDate           (many-to-many link)
                               downloadPriority
                               otherInfo / downloadInfo
```

### 2.1 State Machines

- `publish_pos.state`: `inQueue` ⇄ `stopped` (stopped positions are skipped by the updater).
- `works.state` (download pipeline): `inQueue (or NULL for legacy rows) → downloading →
  done / failed`; `stopped` can be set at any time — schedulers skip it and completion
  callbacks never overwrite it; `downloading` leftovers from crashes are requeued at the
  start of each round.
- Site-side work state is not stored in `state`; the updater keeps it in
  `otherInfo.siteState` (JSON).

### 2.2 Implementation Notes & Pitfalls

- **Composite FKs + DEFERRABLE**: upload's two foreign keys share the `website` column; a
  single ORM flush cannot order parents first, hence `DEFERRABLE INITIALLY DEFERRED` (checked
  at commit; insert order becomes irrelevant, orphans are still rejected). Connection-level
  PRAGMAs: `journal_mode=WAL`, `busy_timeout=30000`, `foreign_keys=ON`.
- **Session expiry pitfall**: `get_db_session()` commits on exit and ORM objects expire
  afterwards. Copy data into dicts inside the session (the claim logic does exactly that).
- **All relationships are viewonly**: upload's two FKs share a column, which makes write
  direction ambiguous — writes always construct `Upload(...)` explicitly; relationships are
  navigation-only.

### 2.3 Migrations

- `schema_version` stores the current version; migration files are
  `src/utils/database/migrations/000N_name.py` providing `apply(engine)`, and **must be
  idempotent** (fresh databases are built by create_all at the latest shape and skip history).
- Standard flow for model changes: edit `models.py` → add `000N_*.py` → bump
  `HEAD_SCHEMA_VERSION` in `database.py`.
- Version resolution: fresh DBs are stamped at HEAD right after create_all; an existing DB
  seen without a version table is stamped at 1 (baseline = the schema shipped with this
  version) and then all later migrations run. 0002 is the first real migration
  (user→publish_pos, including handling of the empty table create_all pre-creates).

## 3. Script Plugin Lifecycle

```
init / System-tab reload / web upload
        │
        ▼
ScriptDispatcher.load()
  ├─ evaluate sources() → file path list (legacy file first + scripts/<kind>/ dir sorted;
  │  re-evaluated on every load, so uploads/deletes are picked up by a rescan)
  ├─ per file ensure_requirements()  parses "# requirements:" headers → detects missing packages
  │  (version-checked when packaging is available) → pip install under a lock (failures are
  │  logged, never blocking)
  ├─ per file load_module_from_file() scans public classes' website attr → routes merged across
  │  files (duplicate sites: first loaded wins with a warning; files without website may
  │  contribute the fallback, at most one)
  └─ only after everything parses are self._routes/_wildcard/_file_routes committed — on
     failure the old routes survive. `sites_by_file()` powers website-conflict detection for
     uploads.
```

- Dispatch: `dispatcher.get(website)` exact match → wildcard fallback → `ScriptRouteError`
  (lists available sites).
- `snapshot()` returns the route table for the System tab.
- Script instances receive injected attributes: `logger` (the SpiderLogger class),
  `config_manager`, `cookie_manager` (classmethod-style).

### 3.1 DownloadWork Contract

```python
def __init__(self, work_info: dict, download_path: str, download_info: dict | None)
def download_it(self) -> str | dict   # str=payload path; dict={path, duration?}
```

`download_path` is decided by the wrapper (see §5.2) and pre-created. A missing path in the
return value is treated as a failure in cache mode.

### 3.2 UpdateUser Contract

```python
def __init__(self, usr: dict, logging)   # usr = {authorId, website, addTime}
def __iter__ / __next__                  # yields dicts:
# workid|workNumber (required), upTime, title, kind, state (→ otherInfo.siteState),
# downloadDate, downloadPriority
```

An existing `upload` link stops the iteration for that position (incremental sync
semantics) — **yield works from newest to oldest**.

## 4. Scheduler Internals

### 4.1 Updater (per site)

```
supervisor thread (5s tick): global do_update on → find sites having non-stopped positions →
    start a runner each
runner: creates the site's own ThreadPool(update_thread) → _site_loop
_site_loop: exits when the site-level do_update is off (supervisor restarts on re-enable) →
    each round: query this site's non-stopped positions → submit one pool task per position
    (staggered by commit_interval ±10%) → wait for the round → sleep update_interval ±10%
    (-1 = keep updating continuously)
```

Per item: insert `works` (IntegrityError = exists, ignored) then `upload`
(IntegrityError = already synced, break). `page_interval` (in-position paging delay) is
resolved per site and injected into the script instance.

### 4.2 Downloader (per site)

```
supervisor thread (5s tick): global do_download on → find pending sites → start a runner each
runner: creates the site's own ThreadPool(download_thread) → _site_loop
_site_loop: exits when the site-level switch is off (supervisor restarts on re-enable) → each round:
    requeue this site's stale downloads → claim loop (this site only, priority desc) →
    pool.submit → wait_for_completion → sleep per download_interval (re-read every round end)
```

- `_claim_next_work(website)`: claim = mark `downloading`; **single-thread claiming is
  race-free**; dicts must be built inside the session.
- `_run_download_task`: resolves per-site use_cache/download_path/etc → instantiates the
  script → `download_it()` → cache mode `_deliver_to_final()` (copy to
  `download_path/<website>/<work>/` + rmtree the cache dir) → `_finish_work`.
- `stop()`: sets the global Event (every sleep is an `Event.wait`, wake-able) + shuts every
  pool down (wait=True, cancel_futures=True). Known noise: if a scheduler thread is exactly
  inside submit when its pool closes, one harmless error line is logged.

### 4.3 Thread Pool

`ThreadPool(ThreadPoolExecutor)`: a semaphore throttles submit (a full pool blocks the
submitter — natural backpressure), plus counters and a polling `wait_for_completion`. Site
pools shut down when their runner exits.

## 5. Config System Internals

- `load_all_configs()`: **build a fresh dict locally → swap it in atomically under the lock**
  (readers never see an empty window during hot reload; a missing directory keeps the old
  config). A single broken file drops only that section with a logged error.
- `_apply_env_overrides()`: replayed after every file reload, memory-only — env always wins
  over files and is never written back.
- `ConfigManager.get(dict_name, key)`: RLock; unknown keys raise `GetUnknownKey`; `${BASE_PATH}`
  in string values is replaced with the work directory.
- `replace_section()`: the write path behind the System-tab config editor (root must be a
  mapping, section must already exist, atomic disk write).
- `site_setting(website, key)` (Downloader): `download.yaml`'s `site.<website> > site.default > code fallback`; override values get `${BASE_PATH}` replacement too.

## 6. Login Proxy Internals

- One `requests.Session` per site (in-process; destroyed on save/cancel) — all Set-Cookies go
  into the jar, the browser only ever sees same-origin responses (bypasses third-party cookie
  restrictions); later requests automatically carry the jar's cookies.
- `_rewrite_html`: absolute/protocol-relative URLs → marker → root-relative
  `href|src|action/...="/x"` prefixed → marker restored + `<base>` injected. The two-step
  marker prevents double-prefixing.
- Known limitations: only server-returned HTML is rewritten; root-relative requests made by
  runtime JS are rescued by the 404 handler (Referer check) via 302; third-party OAuth and
  strict-CSP sites need special handling.
- Concurrency assumption: one user, one session; `requests.Session` is not strictly
  thread-safe — don't log into the same site concurrently.

## 7. Frontend Architecture

`src/server/web/index.html` — one file (no build step, no dependencies), served same-origin
from Flask's `/` route.

- Global state `S = {tab, works, positions, stats, size}`; `api` is a callable with
  `post/put` attached.
- Each tab has `loadX / renderX` functions; tables render into `#table`; row actions use
  event delegation (`data-*` dispatch).
- Filter changes → `reload()` (300 ms debounce); clicking the stats strip mutates filters.
- Known pitfalls: sticky `th` mis-renders in Chromium with `border-collapse` +
  `overflow:hidden` (removed); Playwright automation occasionally swallows clicks on this
  page — in tests, retry clicks in-page via evaluate.

## 8. Testing

```bash
python3 -m pytest tests/          # 124 cases
```

| File | Covers |
|---|---|
| test_models | composite DEFERRABLE FKs, downloadInfo, relationships |
| test_dispatcher | routing/fallback/reload safety/requirements |
| test_config | copy-then-swap atomicity, env overrides, replace_section, ${BASE_PATH} |
| test_queue | claim ordering/state writes/stopped protection/crash recovery/cache wrapper/per-site isolation |
| test_updater | per-site config resolution, per-site scheduling, newest-first yields, page_interval injection |
| test_script_tools | log outlet, site URLs, Selenium assembly stubs, dynamic registration |
| test_e2e | embedded fake site + real scheduling end-to-end |
| test_logger | log caller attribution (instance/classmethod) and monthly rotation |
| test_query_api | filter combinations, pagination, stats |
| test_cookie | HTML rewriting, storage, save flow |
| test_system_api | routes/reload/upload, raw config I/O, website entry CRUD, update-now |
| test_migrations | version stamp idempotence, PRAGMAs, v1→v2 upgrade |

Common patterns: `monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))` to isolate
the work directory; point `DatabaseManager.engine` at a temp SQLite; register blueprints on a
bare Flask app and use `test_client`.

## 9. Extension Guide

**Onboard a new site**: ① add the entry on the Cookie tab → ② log in on the
Cookie tab → ③ upload your scripts (declare `website`, optionally `# requirements:`) →
④ optionally add pacing overrides in `download.yaml` (site section). No restarts needed.

**Add a REST endpoint**: add a route in the relevant blueprint's `_register_routes` (use the
`_err` helper, include `success` in responses) and register it in the API tables of
`docs/user-guide*.md`.

**Add a schema change**: follow §2.3; for a migration test see
`test_migrations.py::test_old_user_table_migrated_to_publish_pos` (build the old schema by
hand → run the runner → assert data and version).

**Conventions**: comments and logs in Chinese; ORM relationships always `viewonly=True`;
convert ORM objects to dicts inside the session; read config via `ConfigManager.get` (gets
${BASE_PATH} and env overrides) and per-site values via `site_setting`.

## 10. Known Limitations (honest list)

- No REST API auth (binds 0.0.0.0, LAN only); cookie files are plaintext.
- Login-proxy sessions are in-process singletons — a multi-worker deployment (gunicorn) would
  split them; `requests.Session` is not strictly thread-safe.
- A crash before the copy step leaves the cache directory behind (re-downloads overwrite it;
  harmless but accumulates — clean manually).
- `download_thread` hot-changes don't apply (restart required).
