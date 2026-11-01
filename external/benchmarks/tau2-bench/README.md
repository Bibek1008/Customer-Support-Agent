# Official tau2-bench data

This directory contains a sparse public-data checkout from the official
[sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench)
repository. Provenance and the selected domains are recorded in
[`PROVENANCE.json`](./PROVENANCE.json); file-level hashes are written to
`download_manifest.json` by the downloader.

The public data payload under `data/` is intentionally ignored by the parent
project's Git configuration. Recreate it from the pinned upstream commit with
PowerShell:

```powershell
.\eval\download_tau2_bench.ps1
```

The sparse checkout omits voice task files, audio payloads, and model weights.
The `banking_knowledge` domain is retained for data inspection; upstream's
released banking benchmark is voice-only and this project does not download the
voice assets needed to run it.
