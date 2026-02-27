# org-timeviz

Generate plots from Org-mode CLOCK entries while keeping Org files as the single
source of truth.

## What it does

* Reads Org files (default: from `org-agenda-files` in `~/.emacs`)
* Parses `CLOCK` lines and associates them with headline path and inherited tags
* Applies time periods and filters from YAML config
* Generates plots and a `summary.json` per report

## Quick start

```bash
conda env create -f environment.yml
conda activate org_timeviz
python -m main
```

or simply

```bash
make run
```

By default it uses:

* config: `configs/default.yaml`
* org sources: `~/.emacs org-agenda-files`
* output: `./outputs/`

## Configuration

The config file is a single YAML (default: `configs/default.yaml`). Reports are
a fixed set (weekly/monthly "last", plus all weeks and all months in the data
range, plus one timeseries). The `reports:` section only configures shared
filters and plot settings; it does not list report names.

* `app.output_dir`: output directory (default `outputs/`)
* `app.log_level`: logging level (e.g. `INFO`)
* `parser.emacs_executable`: Emacs binary to invoke (default `emacs`)
* `org_sources`: where to get Org files (either from `org-agenda-files` in an
  init file, or an explicit list)
* `reports.filters`: include/exclude tags and task regex filters applied to all
  reports
* `reports.plots`:
  * `top_k_tasks`, `top_k_tags`: top-K bars plus one extra "(others)" bin
  * `timeseries_last_n_days`: if null, use all time; otherwise last N days
  * `timeseries_rolling_days`: rolling mean window for the timeseries

TODO status keywords are obtained robustly via the Emacs batch step (from the
init file used for agenda discovery), so task titles in plots exclude states
like TODO/IN-PROGRESS/BLOCKED/etc.

## Outputs

All artifacts are written directly under `outputs/` (no subdirectories). Each
plot also has a matching JSON summary next to it.

* "Last" windows:
  * `by_task_week_last.png` and `by_task_week_last__summary.json` (last 7 days)
  * `by_task_month_last.png` and `by_task_month_last__summary.json` (last 30
    days)
  * same pattern for `by_tags_*`
* Full-range windows (one per period):
  * `by_task_week_YYYY-MM-DD_to_YYYY-MM-DD.png` for each Monday-to-Sunday week
    in the data range
  * `by_task_month_YYYY-MM-DD_to_YYYY-MM-DD.png` for each calendar month in the
    data range
  * same pattern for `by_tags_*`
* Timeseries:
  * `timeseries_daily_total.png` and `timeseries_daily_total__summary.json`
    (last N days if configured, otherwise all time), including a dashed
    horizontal average line

## Extension points

The code is structured so you can add features without changing the CLI or
introducing manual steps.

* Add a new plot type:
  * implement a new function in `org_timeviz/plots.py`
  * call it from `org_timeviz/reports.py` alongside the fixed report set
* Add new aggregations/breakdowns:
  * extend `org_timeviz/aggregate.py` (then plot it)
* Add toggles to enable/disable specific fixed reports:
  * add booleans under `reports.plots` (or a new `reports.enabled` section) and
    gate calls in `reports.py`


## Laundry List

- [ ] filter "by task" by hierarchy level.
- [ ] the timeseries is nice, but maybe a representation that also show
      tasks/tags which have been the focus in each period.
- [ ] get reports tailored to one tag or one specific task
- [ ] visualize each task as a bar fragment, each vertical column is a 24-hour
      day, and x-axes is the time (days)
- [ ] config module can be simplified

## License

Distributed with a GNU GENERAL PUBLIC LICENSE; see LICENSE.

```
Copyright (C) Saeed Gholami Shahbandi
```

NOTE: Portions of this code/project were developed with the assistance of
ChatGPT, a product of OpenAI.
