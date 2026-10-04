# private/

Your own inputs for the private front door. Everything in this folder is gitignored except this
README and `inputs.example.json`, so nothing here is committed or published.

1. Copy `inputs.example.json` to `inputs.json` and edit it (same format as `configs/public/*.json`).
2. Run `python app/run_private.py --config private/inputs.json`.
3. Open the pages with `python -m http.server -d private/site 8000`.

**Personal-time data only. Work data goes through official channels, never a repo.**
