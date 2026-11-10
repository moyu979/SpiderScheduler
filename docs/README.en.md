# SpiderScheduler

A multi-site, plugin-based crawler scheduling system. The framework handles scheduling, the
download queue, state management, login cookies and the web UI; the actual scraping lives in
**user scripts** dispatched by `website` — the framework itself is site-agnostic.

## Core Concepts

- **Publish position (publish_pos)**: a tracked spot on one author's publishing stream for one
  site. The updater walks each position's stream of works; new works automatically enter the
  download queue.
- **Work (works)**: the unit of the download queue; each work can carry its own download
  parameters (`downloadInfo`).
- **User scripts**: two kinds — `UpdateUser` (pages through an author's works) and
  `DownloadWork` (downloads a single work). They live in the work directory's `scripts/`
  folder and can be uploaded, hot-reloaded online, and declare their own pip dependencies.
- **Site isolation**: every site gets its own download scheduler thread (pool size, interval,
  batch limit, cache and paths are configurable per site).

## Quick Start

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Run (work directory ./docker by default, port 8300)
python main.py
# open http://127.0.0.1:8300
```

The first start generates config templates and an empty database in the work directory
automatically.

Docker deployment:

```bash
docker compose up -d --build     # data lives in the named volume spider-data at /data
```

## The Four Tabs

| Tab | What you can do |
|---|---|
| Works | Combined filters (site / multi-state / author / date range / keyword / sort / pagination); clickable site×state stats strip; per-row stop & requeue |
| Positions | Add a publish position (author ID + site dropdown); filter by site; stop/resume tracking per row; per-position work count |
| Cookie | Per-site cookie status; **Login** — the real target-site login page is proxied to you and cookies are captured automatically; delete |
| System | View script routes; hot-reload scripts; upload/view scripts (dependencies auto-installed); edit any config section online (YAML) |

## Script Plugins

```python
# scripts/download_a_work.py
class DownloadWork:
    website = "pixiv"            # declares the site it serves; omit for a single-site fallback

    def __init__(self, work_info, download_path, download_info=None):
        # download_path: this task's own directory (cache workdir when caching is on,
        #                the final directory when off) — just write your data here
        ...

    def download_it(self):
        ...                       # write data into download_path, return the payload path
```

A script header may declare `# requirements: <package>`; the framework auto-installs missing
packages before loading. The full script contract, state machines and configuration are
documented in the [User Guide](user-guide.en.md) and the [Dev Guide](dev-guide.en.md).

## Repository Layout

```
SpiderScheduler/
├── main.py            # entry point (--repl CLI, --basepath work directory)
├── src/               # schedulers, APIs, frontend, infrastructure
├── tests/             # pytest suite (124 cases)
├── docker/            # default work directory (runtime data, not committed)
├── docs/              # this documentation
├── Dockerfile / docker-compose.yml / .dockerignore
└── ARCHITECTURE.md    # architecture details (kept in sync with the code)
```

## Documentation

- [User Guide](user-guide.en.md): running the app, all four tabs, REST API reference,
  configuration, troubleshooting.
- [Dev Guide](dev-guide.en.md): architecture layers, script contract, state machines,
  database & migrations, testing, extension guide.
- [ARCHITECTURE.md](../ARCHITECTURE.md): architecture design document (kept in sync with code).
