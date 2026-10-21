# private/

Your own inputs for the private front door. Everything in this folder is gitignored except this
README and `inputs.example.json`, so nothing here is committed or published.

1. Copy `inputs.example.json` to `inputs.json` and edit it (same format as `configs/public/*.json`).
2. Run `python app/run_private.py --config private/inputs.json`.
3. Open the pages with `python -m http.server -d private/site 8000`.

**Backtest your own history:** save it as `history.csv` here (same layout as the template from the
planner's **Download the template**), then run step 2 again. Add `--times flown` to time each week by
its flown first launch and last land instead of the planned ones, or `--history path/to/file.csv` for
another file. The summary prints in the terminal; `data/backtest.json` and `data/backtest_weeks.csv`
hold the full results, and the private Method page shows the backtest as Done locally.

**Personal-time data only. Work data goes through official channels, never a repo.**
