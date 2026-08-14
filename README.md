# PubMed Phase 1 Screening Export

**Turn a PubMed search into a spreadsheet with one command.** No accounts, no keys, nothing to install.

## What it does

This tool searches [PubMed](https://pubmed.ncbi.nlm.nih.gov/) for you and saves every match to a CSV, with authors, title, abstract, journal, year, DOI, and link all filled in. 

Open the CSV in Excel, Numbers, or Google Sheets and start screening. A real sample is in [`example_outputs/`](example_outputs/).

## Use it

You need **Python 3** (already on Mac and Linux; [get it here](https://www.python.org/downloads/) on Windows).

1. Download this project (green **Code** button, then **Download ZIP**, then unzip).
2. Open a terminal in the folder that contains `pubmed_screening.py`.
3. Run:

```bash
python3 pubmed_screening.py
```

When it finishes, a file like `pubmed_screening_2026-08-13_194829.csv` appears in the folder. Every run makes a new file, so nothing gets overwritten.

## Searching

Put your search in quotes after `--query`. This is exactly what you'd type into the [PubMed website](https://pubmed.ncbi.nlm.nih.gov/) search box, so if it works there, it works here.

```bash
python3 pubmed_screening.py --query "(migraine[Title/Abstract]) AND children"
```

## All options

Add any of these after the command. Combine as many as you like.

| Option | What it does |
| --- | --- |
| `--query "..."` | Your PubMed search, in quotes (same as the website search box). |
| `--simple` | Export only Authors, Title, and Abstract (no other columns). |
| `--sort recent` | Result order. Choices: `recent` (default), `relevance`, `pubdate`, `author`, `journal`. |
| `--start-year 2015` | Earliest publication year to include (default: 2019). |
| `--end-year 2024` | Latest publication year to include (default: this year). |
| `--output name.csv` | Save to a filename you choose. |
| `--help` | List every option and exit. |

For example, a simple export of the 10 most recent years, sorted by best match:

```bash
python3 pubmed_screening.py --simple --start-year 2015 --sort relevance
```

## Good to know

- **How it works:** PubMed's own free service finds your matches and hands back their details. Handles up to 10,000 articles per run.
- **Contact email (optional):** PubMed likes to know who's asking. To add yours, put `--email you@example.com` after the command. It stays private.
- **No results?** Try the search on the [PubMed website](https://pubmed.ncbi.nlm.nih.gov/) first. If it works there, paste the same thing after `--query`.

## License

[MIT](LICENSE), free to use, change, and share.
