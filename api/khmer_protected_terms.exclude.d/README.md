# Directory form of `../khmer_protected_terms.exclude.txt`

Same purpose as the single `khmer_protected_terms.exclude.txt` file next
to this directory — terms to suppress for this API deployment — but as a
*folder* of `.txt` files instead of one file. Every `*.txt` file placed
directly in this directory (not recursive) is loaded and merged, in
filename order.

Format: identical to `khmer_protected_terms.exclude.txt` — one term per
line, blank lines and `#` comments ignored. Exclusion always wins over
injection for the same term, whether the term came from the shared
package, `../khmer_protected_terms.txt`, or `../khmer_protected_terms.d/`.

Wire it in before starting the API:

```bash
export AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR=api/khmer_protected_terms.exclude.d
uvicorn app.main:app --reload --port 8000
```

See [`../../docs/protected-terms-guide.md`](../../docs/protected-terms-guide.md)
for the full reference and the classification rubric.
