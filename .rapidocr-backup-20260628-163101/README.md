# Command Zone You Rock

A repeatable scanner and review tool for cataloging the **“You Rock”** shout-outs in The Command Zone podcast playlist.

Playlist:

```text
https://www.youtube.com/playlist?list=PLyLzs6vB3Xk7u8L3xGBsM5wo8Ms5jUIxh
```

The project keeps the canonical data in CSV and generates a human-readable GitHub page at [`YOU_ROCK.md`](YOU_ROCK.md).

## How it works

1. `yt-dlp` lists the playlist and retrieves metadata only for unprocessed videos.
2. The scanner retrieves English captions and searches rolling transcript windows for phrases such as “you rock.”
3. Candidate timestamps are added to `data/shoutouts.csv` as `pending`.
4. The optional capture step downloads only a short section around each timestamp, samples frames, crops the lower portion of the frame, and runs Tesseract OCR.
5. A local browser review app lets you correct the name and mark each result `verified` or `rejected`.
6. Verified rows are published to `YOU_ROCK.md`.

The first known result from the supplied screenshot is already included:

- Ben Wyrosdick
- Episode 745
- 1:19:46

## Repository layout

```text
.
├── config.toml
├── data/
│   ├── shoutouts.csv       # Canonical shout-out dataset
│   └── videos.csv          # Processing registry
├── screenshots/            # Optional local OCR evidence frames
├── src/yourock/            # Scanner, OCR, Markdown builder, review app
├── tests/
├── YOU_ROCK.md             # Generated public list
└── .github/workflows/
    ├── tests.yml
    └── update.yml
```

## Windows setup

Python 3.12 is recommended. FFmpeg and Tesseract are required only for screenshot capture and OCR.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
yourock doctor
```

Install FFmpeg and Tesseract through `winget` when needed:

```powershell
winget install --id Gyan.FFmpeg
winget install --id UB-Mannheim.TesseractOCR
```

Open a new PowerShell window after installation if either program is not found on `PATH`.

## Put it on GitHub

Create an empty GitHub repository named `command-zone-you-rock`, then run from this project folder:

```powershell
git init
git add .
git commit -m "Initial Command Zone You Rock scanner"
git branch -M main
git remote add origin https://github.com/YOUR-USER-NAME/command-zone-you-rock.git
git push -u origin main
```

Replace `YOUR-USER-NAME` with your GitHub account name.

## First test run

Scan the next ten unprocessed playlist videos:

```powershell
yourock scan --limit 10
```

Capture and OCR up to ten pending candidates:

```powershell
yourock capture --limit 10
```

Start the review application:

```powershell
yourock review
```

Then open:

```text
http://127.0.0.1:5000
```

Verify a result only after checking the linked YouTube timestamp.

## Initial backlog

The scanner saves after every video, so it can be stopped and restarted safely.

Process the complete unprocessed backlog:

```powershell
yourock scan --limit 0
```

Capture all pending candidates:

```powershell
yourock capture --limit 0
```

Because the playlist contains many long episodes, start with small batches before launching the full backlog.

## Routine update

After the initial backlog, this processes only playlist videos absent from `data/videos.csv`:

```powershell
git pull
yourock scan --limit 10 --retry-errors
yourock capture --limit 10
yourock review
git add data YOU_ROCK.md
git commit -m "Update You Rock shout-outs"
git push
```

Screenshots are stored as small lower-third evidence crops and can be committed with the CSV.

## Useful commands

Scan one video again:

```powershell
yourock scan --video ftCPe3Yxztk --rescan-complete
```

Capture one candidate again:

```powershell
yourock capture --candidate ftCPe3Yxztk-4786-manual --all
```

Retry videos whose transcript retrieval previously failed:

```powershell
yourock scan --limit 10 --retry-errors
```

Rebuild Markdown after editing the CSV manually:

```powershell
yourock build
```

## CSV status values

`data/shoutouts.csv` uses:

- `pending`: transcript match awaiting human review
- `verified`: confirmed shout-out included in `YOU_ROCK.md`
- `rejected`: false positive retained to prevent repeated work

`data/videos.csv` uses:

- `complete`: transcript searched successfully, including episodes with zero matches
- `retry`: retrieval failed and may be retried later

## Configuration

Edit `config.toml` to change:

- Playlist URL
- Transcript phrase patterns
- Match deduplication window
- Clip length around a candidate
- OCR crop region
- Maximum downloaded video height

The default transcript expression also matches phrases such as “you guys really rock.”

## GitHub Actions

The scheduled updater checks a small number of unprocessed videos twice per week and commits new transcript candidates when it succeeds. It deliberately does not verify names; run the local capture and review steps before a candidate appears in `YOU_ROCK.md`. The workflow can also be started manually from the Actions tab.

YouTube may rate-limit or block requests from shared cloud-runner IP addresses. The local commands remain the reliable path for the initial backlog and for retrying failed episodes.

## Content note

This repository stores indexes, timestamps, metadata, and optional short evidence crops. It does not archive full podcast episodes. Review YouTube’s terms and the rights holder’s policies before redistributing media or captions.
