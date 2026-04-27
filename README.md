# org-timeviz

Generate plots from Org-mode CLOCK entries while keeping Org files as the single
source of truth.

## What it does

* Reads Org files (default: from `org-agenda-files` in `~/.emacs`)
* Parses `CLOCK` lines and associates them with headline path and inherited tags
* Applies time periods and filters from YAML config
* Resolves configured time-bucket allocations from tags
* Generates plots and a `summary.json` per report

## Configuration

The config file is a single YAML (default: `configs/default.yaml`). Reports are
a fixed set (weekly/monthly "last", plus all weeks and all months in the data
range, plus one timeseries and one monthly time-bucket trend report). The
`reports:` section only configures shared filters and plot settings; it does
not list report names.

* `app.output_dir`: output directory (default `outputs/`)
* `app.log_level`: logging level (e.g. `INFO`)
* `parser.emacs_executable`: Emacs binary to invoke (default `emacs`)
* `org_sources`: where to get Org files (either from `org-agenda-files` in an
  init file, or an explicit list)
* `reports.filters`: include/exclude tags and task regex filters applied to all
  reports
* `reports.plots`:
  * `top_k_tasks`: top-K tasks plus one extra "(others)" bin
  * `top_k_tags`: top-K time buckets plus one extra "(others)" bin
  * `timeseries_last_n_days`: if null, use all time; otherwise last N days
  * `timeseries_rolling_days`: rolling mean window for the timeseries
* `time_buckets`:
  * `other_bucket`: fallback bucket when no time-bucket tag matches
  * `bucket_order`: canonical time-bucket names and display/order priority
  * `tag_to_bucket`: mapping from raw Org tags to canonical time buckets
  * `resolution`: arbitration logic for tasks matching multiple time buckets

TODO status keywords are obtained robustly via the Emacs batch step (from the
init file used for agenda discovery), so task titles in plots exclude states
like TODO/IN-PROGRESS/BLOCKED/etc.

## Outputs

Artifacts are written under `outputs/assets/`, and `outputs/index.html` links to
them. Each plot also has a matching JSON summary next to it.

* "Last" windows:
  * `by_task_week_last_YYYY-MM-DD_to_YYYY-MM-DD.png` and
    `by_task_week_last_YYYY-MM-DD_to_YYYY-MM-DD__summary.json`
  * `by_task_month_last_YYYY-MM-DD_to_YYYY-MM-DD.png` and
    `by_task_month_last_YYYY-MM-DD_to_YYYY-MM-DD__summary.json`
  * `by_time_bucket_week_last_YYYY-MM-DD_to_YYYY-MM-DD.png` and
    `by_time_bucket_week_last_YYYY-MM-DD_to_YYYY-MM-DD__summary.json`
  * `by_time_bucket_month_last_YYYY-MM-DD_to_YYYY-MM-DD.png` and
    `by_time_bucket_month_last_YYYY-MM-DD_to_YYYY-MM-DD__summary.json`
  * `calendar_week_last_YYYY-MM-DD_to_YYYY-MM-DD.png` and
    `calendar_week_last_YYYY-MM-DD_to_YYYY-MM-DD__summary.json`
  * `calendar_month_last_YYYY-MM-DD_to_YYYY-MM-DD.png` and
    `calendar_month_last_YYYY-MM-DD_to_YYYY-MM-DD__summary.json`

* Full-range windows (one per period):
  * `by_task_week_YYYY-MM-DD_to_YYYY-MM-DD.png`
  * `by_task_month_YYYY-MM-DD_to_YYYY-MM-DD.png`
  * `by_time_bucket_week_YYYY-MM-DD_to_YYYY-MM-DD.png`
  * `by_time_bucket_month_YYYY-MM-DD_to_YYYY-MM-DD.png`
  * `calendar_week_YYYY-MM-DD_to_YYYY-MM-DD.png`
  * `calendar_month_YYYY-MM-DD_to_YYYY-MM-DD.png`

* Time series:
  * `timeseries_daily_total.png` and
    `timeseries_daily_total__summary.json`
  * the main line shows actual daily hours for days with logged time
  * the dashed average lines show:
    * all-time average per workday across the plotted range
    * trailing weekly average per workday (7 calendar days)
    * trailing monthly average per workday (30 calendar days)
  * weekend and other zero-hour days are included in the averaging windows
    where relevant, but the main daily line is drawn only for days with logged
    time
  * weekend hours are included in the numerator of weekly/monthly/all-time
    averages, but weekends are not counted in the denominator

* Monthly time-bucket trend report:
  * `time_buckets_monthly.png` and `time_buckets_monthly__summary.json`

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

- [ ] the timeseries is nice, but maybe a representation that also show
      tasks/tags which have been the focus in each period.

## License

Distributed with a GNU GENERAL PUBLIC LICENSE; see LICENSE.

```
Copyright (C) Saeed Gholami Shahbandi
```

NOTE: Portions of this code/project were developed with the assistance of
ChatGPT, a product of OpenAI.
