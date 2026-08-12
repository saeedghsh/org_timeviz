# org-timeviz

Generate plots from Org-mode CLOCK entries while keeping Org files as the single
source of truth.

## What it does

* Reads Org files (default: from `org-agenda-files` in `~/.emacs`)
* Parses `CLOCK` lines and associates them with headline path and inherited tags
* Applies time periods and filters from YAML config
* Resolves configured time-bucket allocations from tags
* Generates static plots, an interactive time-bucket dashboard, an HTML index,
  and JSON summaries for static reports

## Running and refreshing reports

The recommended workflow is:

```bash
make serve
```

Then open:

```text
http://127.0.0.1:8000/
```

`make serve` first generates the reports, then starts a local HTTP server bound
only to `127.0.0.1`. The generated `index.html` has a **Refresh reports** button
at the top. Clicking it regenerates all report artifacts using the same config
and reloads the page when generation finishes. Static files are served with
caching disabled so regenerated plots are fetched immediately.

Use a different port when needed:

```bash
make serve SERVE_PORT=8080
```

Stop the server with `Ctrl-C`.

The old manual workflow still works:

```bash
make run
firefox outputs/index.html
```

When `index.html` is opened directly through `file://`, the refresh button is
disabled because browsers cannot invoke the local report generator from a file
URL. In that mode, run `make run` again whenever the reports need updating.

## Other catalogue

When new Org tags are not mapped under `time_buckets.tag_to_bucket`, time may
start accumulating under the `other` time bucket. To inspect which unmapped tags
are contributing to `other`, run:

```bash
make other_catalogue
```

This writes `other_catalogue.csv` under the configured output directory. The CSV
has two columns:

* `tag`: an unmapped Org tag found on records assigned to `other`
* `hours`: total clocked hours for records carrying that tag

Only records that resolve fully to the configured `other_bucket` are included.
If a record has no tags at all, it is reported under `(no-tag)`.

## Configuration

The config file is a single YAML (default: `configs/default.yaml`). Report types
are fixed in code: a rolling 30-day task calendar, calendar-month task views, a
daily working-hours timeseries, a monthly time-bucket trend, and the interactive
time-bucket dashboard. The `reports:` section only configures shared filters and
plot settings; it does not list report names.

* `app.output_dir`: output directory (default `outputs/`)
* `app.log_level`: logging level (e.g. `INFO`)
* `org_sources`: where to get Org files (either from `org-agenda-files` in an
  Emacs init file, or an explicit list)
* `reports.filters`: include/exclude tags and task regex filters applied to all
  reports
* `reports.plots`:
  * `top_k_tasks`: top-K tasks used by the task calendar legend
  * `timeseries_last_n_days`: if null, use all time; otherwise last N days
* `time_buckets`:
  * `other_bucket`: fallback bucket when no time-bucket tag matches
  * `bucket_order`: canonical time-bucket names and display/order priority
  * `tag_to_bucket`: mapping from raw Org tags to canonical time buckets
  * `resolution`: arbitration logic for tasks matching multiple time buckets

TODO status keywords are obtained robustly via the Emacs batch step, so task
titles in plots exclude states like TODO/IN-PROGRESS/BLOCKED/etc.

## Outputs

Artifacts are written under `outputs/assets/`, and `outputs/index.html` is the
landing page. Static plots have matching JSON summaries next to them.

Generated artifacts currently include:

* `interactive__time_bucket.html`: linked interactive calendar and time-bucket
  histogram. The histogram follows the calendar's visible date range.
* `calendar_view__task__month__YYYY-MM-DD_to_YYYY-MM-DD__latest.png`: rolling
  30-day task calendar and matching summary JSON.
* `calendar_view__task__month__YYYY-MM-DD_to_YYYY-MM-DD.png`: one task calendar
  per calendar month and matching summary JSON.
* `timeseries__daily_working_hours__day__all_time.png`: daily working-hours
  timeseries and matching summary JSON. If `timeseries_last_n_days` is set, the
  filename contains that rolling date range instead of `all_time`.
* `timeseries__time_bucket__month__all_time.png`: monthly time-bucket trend and
  matching summary JSON.

In the interactive calendar, each clocked block is colored by its dominant
resolved time bucket after arbitration. If arbitration splits a task across
multiple buckets, the largest resolved share determines the calendar color,
while the linked histogram uses the full allocation fractions.

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

## License

Distributed with a GNU GENERAL PUBLIC LICENSE; see LICENSE.

```
Copyright (C) Saeed Gholami Shahbandi
```

NOTE: Portions of this code/project were developed with the assistance of
ChatGPT, a product of OpenAI.
