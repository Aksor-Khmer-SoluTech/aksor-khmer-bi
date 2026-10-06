# Directory form of `../khmer_protected_terms.txt`

Same purpose as the single `khmer_protected_terms.txt` file next to this
directory — project-specific terms to inject for this API deployment —
but as a *folder* of `.txt` files instead of one file. Every `*.txt` file
placed directly in this directory (not recursive) is loaded and merged,
in filename order; drop in a new file (e.g. `customer_acme.txt`,
`branch_names.txt`) any time without touching an env var or restarting
config, only the container/process.

Format: identical to `khmer_protected_terms.txt` — one term per line,
blank lines and `#` comments ignored.

Wire it in before starting the API:

```bash
export AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR=api/khmer_protected_terms.d
uvicorn app.main:app --reload --port 8000
```

Both mechanisms (the single file and this directory) can be active at
the same time — their terms are simply merged. See
[`../../docs/protected-terms-guide.md`](../../docs/protected-terms-guide.md)
for the full inject/exclude reference and the classification rubric for
what's worth adding.
