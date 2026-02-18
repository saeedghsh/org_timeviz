# org-timeviz

Generate plots from Org-mode CLOCK entries while keeping Org files as the single source of truth.

## What it does

* Reads Org files (default: from `org-agenda-files` in `~/.emacs`)
* Parses `CLOCK` lines and associates them with headline path and inherited tags
* Applies time periods and filters from YAML config
* Generates plots and a `summary.json` per report

## Quick start

```bash
conda env create -f environment.yml
conda activate org_timeviz
python -m entry_point.generate_reports
```

By default it uses:

* config: `configs/default.yaml`
* org sources: `~/.emacs org-agenda-files`
* output: `./outputs/`

## Configuration

Edit `configs/default.yaml`:

* `org_sources.mode`:
  * emacs: read `org-agenda-files` from an Emacs init file
  * explicit: use an explicit list of org files
* periods: reusable named date windows (`last_n_days`, `range`, `this_week`, etc.)
* reports: each report picks one period, optional filters, and a list of plot kinds

## Outputs

Each report writes into:

```console
outputs/<report_name>/
```

Typical files:

* `bar_by_tag.png`
* `bar_by_task.png`
* `timeseries_daily_total.png`
* `summary.json`

## Extension points

If you want a new plot type:

* add a new function in `org_timeviz/plots.py`
* register it in `org_timeviz/reports.py`
* add it to `configs/default.yaml`

No intermediate data is stored on disk (only final report artifacts).

## Laundry List

- [ ] filter "by task" by hierarchy level.
- [ ] the timeseries is nice, but maybe a representation that also
      show tasks/tags which have been the focus in each period.

## License

Distributed with a GNU GENERAL PUBLIC LICENSE; see LICENSE.

```
Copyright (C) Saeed Gholami Shahbandi
```

NOTE: Portions of this code/project were developed with the assistance of ChatGPT, a product of OpenAI.
