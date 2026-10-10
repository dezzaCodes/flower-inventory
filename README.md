# Flower Inventory

**Live site: https://dezzacodes.github.io/flower-inventory/**

A sortable, filterable page of every flower in the inventory spreadsheet, with photos.

- `index.html` is the whole site. Its data sits in the `flower-data` JSON block.
- `money.html` is the Money page: income, expenses and the profit or loss. Its figures are not in this public repository. They live in `ledger.json` in the private repo `dezzaCodes/flower-ledger`, which the page reads and writes through the GitHub API. Each device is connected once with a fine-grained token that has **Contents: Read and write** on that repo only, and the token stays in that browser.
- `images.json` holds the table thumbnails, resized to 360px WebP.
- `photos/` holds a high-resolution copy of each photo (up to 2400px, WebP) for the detail panel. Files are named by a hash of the original, so unchanged photos aren't re-encoded, and unused ones are deleted on sync.
- `sync.py` rebuilds all of these from the Google Sheet. It reads the sheet ID from the `SHEET_ID` environment variable.
- `.github/workflows/sync.yml` runs `sync.py` every day at 19:00 UTC (6am Sydney) and commits any changes, which republishes the site through GitHub Pages. Run it by hand from the **Actions** tab with **Run workflow**.

The sheet must stay shared as "Anyone with the link can view", and the sheet ID is stored as the repository secret `SHEET_ID`.
