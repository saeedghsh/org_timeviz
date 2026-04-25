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
* time series:
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


## Time buckets from tags

This project can use Org tags not only as semantic metadata, but also as inputs for
time-bucket reporting.

The idea is simple:

* tasks keep their normal tags
* some tags are also recognized as "time-bucket tags"
* those tags are mapped to canonical reporting buckets through
  `time_buckets.tag_to_bucket`
* the monthly time-bucket report aggregates clocked time using those mapped
  buckets

This is a retrofit-friendly design. It lets tags continue to describe the task,
while also making it possible to produce higher-level time-allocation reports.

A task does not need to have a time-bucket tag. If none of its tags map to a
configured time bucket, its time is assigned to the configured `other_bucket`.

Multiple tags may also map to the same canonical bucket. For example,
`holidays` and `vacations` can both map to `holidays_vacations`.

### Why arbitration is needed

Some tasks may carry more than one tag that maps to a time bucket. This happens
when tags are semantically meaningful in more than one way. For example, a task
may be related both to university supervision and to an industrial partner.

In those cases, the reporting layer must decide how to allocate time across the
matching buckets. This decision is called *arbitration*.

Importantly, arbitration is separate from plotting. The plotting code only sees
final bucket allocations. The logic for resolving ambiguous tag combinations is
configured under `time_buckets.resolution`.

### Arbitration strategies

Two strategies are supported:

* `priority`
  * exactly one bucket is selected
  * the first matching bucket in `priority_order` wins

* `split_weighted`
  * time is split across all matched buckets
  * weights come from `weights`
  * if no weights are given for the matched buckets, each bucket gets weight `1`,
    which means an equal split

Resolution works like this:

* map raw tags to canonical buckets
* if zero buckets match, assign all time to `other_bucket`
* if one bucket matches, assign all time to that bucket
* if multiple buckets match:
  * try `rules` from top to bottom
  * the first matching rule wins
  * if no rule matches, use the default strategy under
    `time_buckets.resolution`

### Example rules

Below are two example rules.

The first rule splits time between `alfa_laval` and `msc` with a 3:1 weighted
split:

```yaml
time_buckets:
    resolution:
    default_strategy: priority
    priority_order:
        - alfa_laval
        - pride
        - tooling
        - ml_tooling_tutorial
        - aim_flix
        - msc
        - hh
        - holidays_vacations
        - other
    weights: {}
    rules:
        - name: split_alfa_laval_and_msc
        match_all_tags:
            - alfa_laval
            - msc
        strategy: split_weighted
        weights:
            alfa_laval: 3
            msc: 1
```

The second rule resolves the same ambiguity by always assigning the time to
`alfa_laval`:

```yaml
time_buckets:
    resolution:
    rules:
        - name: prefer_alfa_laval_over_msc
        match_all_tags:
            - alfa_laval
            - msc
        strategy: priority
        priority_order:
            - alfa_laval
            - msc
```

In practice, this lets you keep tags semantically honest while still producing a
clear and configurable reporting view of time allocation.

## Laundry List

- [ ] plots "by tag" must be only for tags that are exclusive, otherwise it
  doesn't give a meaningful sense of time.
- [ ] sort under each heading by "last", "most_recent", "most_recent - 1", ...
  Right now it is "last", "first_ever", "first_ever + 1", ...
- [ ] filter "by task" by hierarchy level.
- [ ] the timeseries is nice, but maybe a representation that also show
      tasks/tags which have been the focus in each period.
- [ ] get reports tailored to one tag or one specific task
- [ ] config module can be simplified

## License

Distributed with a GNU GENERAL PUBLIC LICENSE; see LICENSE.

```
Copyright (C) Saeed Gholami Shahbandi
```

NOTE: Portions of this code/project were developed with the assistance of
ChatGPT, a product of OpenAI.
