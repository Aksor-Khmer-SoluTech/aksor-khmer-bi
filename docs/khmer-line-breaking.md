# Why Khmer text breaks differently across renderers

Khmer is normally written **without spaces between words**. Line-breaking
and justify therefore depend entirely on whether the rendering engine knows
where word boundaries actually are — a plain whitespace-based line breaker
(the kind most web/PDF renderers use) treats an entire unspaced sentence as
one unbreakable token.

## What we verified, directly

**WeasyPrint (Pango layout):** given the unspaced sentence

```
កម្ពុជាជាប្រទេសមួយស្ថិតនៅតំបន់អាស៊ីអាគ្នេយ៍មានទីរាជធានីគឺភ្នំពេញដែលជាមជ្ឈមណ្ឌលនយោបាយសេដ្ឋកិច្ចវប្បធម៌...
```

WeasyPrint rendered it as a single line that overflowed straight off the
page — no wrap at all. Pango classifies Khmer as a "complex context" script
(Unicode UAX #14) that needs a dictionary to find break points, and has no
such dictionary built in for Khmer.

**LibreOffice (Writer's layout engine):** the same sentence, same font,
wrapped correctly into multiple lines and justified evenly. LibreOffice
bundles ICU, which ships an actual maintained Khmer word-break dictionary.

**ICU directly, via PyICU** (used by `aksor_khmer_ocr_segmenter`):

```python
import icu
bi = icu.BreakIterator.createWordInstance(icu.Locale("km"))
bi.setText(text)
```

produces the same correct segmentation:

```
កម្ពុជា | ជា | ប្រទេស | មួយ | ស្ថិតនៅ | តំបន់ | អាស៊ី | អាគ្នេយ៍ | មាន | ទី | រាជធានី | គឺ | ភ្នំពេញ
```

confirmed against increasingly long/unspaced real-world input (a full tax
notice address field), not just the short example above.

## The fix, and why it's not a dictionary we maintain

Rather than hand-build and maintain a Khmer word list, `aksor_khmer_ocr_segmenter`
uses ICU's own dictionary via PyICU — the same open-source, linguist-curated
data LibreOffice already relies on. This sidesteps license/quality/upkeep
questions a homemade word list would raise.

`aksor_khmer_ocr_segmenter.insert_breaks()` re-joins ICU's word boundaries with an
invisible zero-width space (`U+200B`) by default:

```python
from aksor_khmer_ocr_segmenter import process_text
process_text(unspaced_text)  # ZWSP inserted at every word boundary
```

This gives **any** renderer real break points without changing how the text
visually looks — the traditional unspaced Khmer appearance is preserved.

## Known limitation: transliterated names/loanwords

> For the step-by-step procedure for adding a new protected term, the
> classification rubric, and the full current catalog organized by
> category, see
> [`protected-terms-guide.md`](protected-terms-guide.md).

ICU's Khmer dictionary is built for native Khmer vocabulary. For
transliterated foreign names and loanwords — which don't follow native
morphology — it sometimes gets the boundary wrong, splitting mid-syllable.
Confirmed against PyICU 2.16.2 / ICU4C 78.3:

| Input | ICU's raw segmentation | Correct? |
|---|---|---|
| `ឥណ្ឌូនេស៊ី` (Indonesia) | `ឥណ្ឌូ / នេ / ស៊ី` | No |
| `ប៊ុនថន` (Bhutan) | `ប៊ុ / ន / ថន` | No |
| `ម៉ារី` (Mary) | `ម៉ា / រី` | No |
| `រ៉ូប៊ឺត` (Robert) | `រ៉ូប៊ឺ / ត` | No |
| `ឥវ៉ាន់` (Ivan) | `ឥវ៉ាន់` | Yes |
| `អ៊ីស្រាអែល` (Israel) | `អ៊ីស្រាអែល` | Yes |
| `អូស្ត្រាលី` (Australia) | `អូស្ត្រាលី` | Yes |
| `បារាំង` (France) | `បារាំង` | Yes |

(A broader survey across country/city names, personal names, surnames,
science/tech loanwords, brand names, and legal/Pali-Sanskrit formal
vocabulary found 84 mis-split cases — see `protected_terms.PROTECTED_TERMS`
for the full, current list with per-entry comments showing the observed
wrong split. A few entries are borderline: the split lands on a real bound
suffix like ភាព "-ness" or ដ្ឋាន "department", so each half is technically a
valid word — included anyway since they're common in formal documents.)

This is version/dictionary-dependent: a different ICU/CLDR build could
correct these cases, or start mis-splitting a currently-correct one (e.g.
`ឥវ៉ាន់`). There is no dictionary-level fix available to us short of
patching ICU's own data, which is out of scope.

### Mitigation: a small, explicit exception list

`aksor_khmer_ocr_segmenter.protected_terms.PROTECTED_TERMS` is a short,
hand-curated list of specific transliterated terms we've concretely
observed ICU mis-splitting. `segment()` re-merges any run of adjacent ICU
tokens that exactly reconstitutes one of these terms, before boundaries are
handed to `insert_breaks()`.

`protected_terms` is a package, split one module per category, so each list
stays easy to scan: `countries_places.py` (foreign country/city names),
`khmer_places.py` (Cambodian domestic district/street/development names —
found via an end-to-end OCR round trip on a real property-tax address
field, not synthetic testing), `personal_names.py`, `surnames.py`,
`loanwords_science_tech.py`, `brands_orgs.py`, and `legal_formal.py`.
`protected_terms/__init__.py` concatenates all of them into the single
`PROTECTED_TERMS` tuple `segmenter.py` consumes. Current total: 106 terms.

This is deliberately **not** a general Khmer word dictionary and is not
meant to grow into one — see "The fix, and why it's not a dictionary we
maintain" above for why we rejected that approach for the general case. The
exception list only exists to patch specific, observed, high-confidence
failures in transliteration handling; entries should only be added when a
concrete mis-split has been reproduced and pinned with a regression test
(see `tests/test_segmenter.py`).

If you hit a new transliterated name/loanword that ICU splits incorrectly,
add it to the matching category module under `protected_terms/` (or a new
module if it doesn't fit an existing one) with a comment describing the
observed wrong split. `tests/test_segmenter.py` parametrizes over
`PROTECTED_TERMS`, so the regression test is automatic — no test file
changes needed.

### Injecting (and excluding) extra terms from a file, without editing Python

Project-specific terms (a company's own name, local staff names, a
particular development's spelling) don't belong hard-coded into this
package. `protected_terms/loader.py` provides two independent, symmetric
mechanisms for this, both accepting a `.txt` file (one term per line,
blank lines and `#`-comments ignored) or a `.json` file (a JSON array of
strings, or `{"terms": [...]}`) — format picked by file extension:

- **Inject** — add extra terms `segment()` should treat as unbreakable, on
  top of the built-in `PROTECTED_TERMS` (doesn't replace it). See
  `samples/protected_terms_example.txt` / `.json`.
- **Exclude** — remove specific terms (built-in, env-injected, or from an
  inject file) from the merge set for a run, reverting to ICU's original
  (unmerged) behavior for just those terms. Useful when a built-in term
  turns out wrong for your data, without forking the package. See
  `samples/excluded_terms_example.txt`. If the same term is both injected
  and excluded in one call, **exclusion wins**.

Each mechanism has the same two ways to supply a file:

- **Environment variable** — set `AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` (inject)
  or `AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE` (exclude) to a path (or several,
  `os.pathsep`-separated: `:` on macOS/Linux, `;` on Windows). Read once
  when `aksor_khmer_ocr_segmenter.segmenter` is imported, so it applies to every
  `segment()`/`insert_breaks()`/`process_text()`/`process_image()` call
  and the CLI automatically, with no extra argument:

  ```bash
  export AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE=/etc/myapp/khmer_terms.txt
  export AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE=/etc/myapp/khmer_exclusions.json
  ```

- **Explicit argument / flag** — pass `extra_terms_file=<path or list of
  paths>` and/or `exclude_terms_file=<path or list of paths>` to
  `segment()`, `insert_breaks()`, `process_text()`, or `process_image()`,
  or `--protected-terms-file PATH` / `--exclude-terms-file PATH`
  (both repeatable) on the CLI, for a one-off change scoped to that call
  only:

  ```bash
  aksor-khmer-ocr-segment --text "..." --protected-terms-file my_terms.txt
  aksor-khmer-ocr-segment --text "..." --exclude-terms-file my_exclusions.json
  ```

  ```python
  from aksor_khmer_ocr_segmenter import process_text
  process_text(text, extra_terms_file="my_terms.txt")
  process_text(text, exclude_terms_file="my_exclusions.json")
  ```

Environment-variable and call-scoped sources compose (both apply
together). A missing file raises `FileNotFoundError`, and malformed JSON
content raises `ValueError`, immediately rather than silently
segmenting/excluding nothing.

See [`protected-terms-guide.md`](protected-terms-guide.md) for the
standard procedure for deciding whether a term belongs in this package's
built-ins versus a project-local inject file.

We deliberately don't pin an exact ICU4C version in `requirements.txt` —
`PyICU` doesn't control which ICU4C it links against, so a hard pin would
give false confidence without preventing drift. Instead, the version this
behavior was observed on is recorded in `protected_terms.py` and above, so a
failing regression test after an environment upgrade can be traced back to
an actual ICU/CLDR change.

### Related but separate: OCR recognition errors

An end-to-end round trip (WeasyPrint-rendered HTML → `pdftoppm` →
Tesseract `khm` → `process_image()`) surfaced a different class of
problem that `protected_terms` cannot fix: Tesseract sometimes
mis-recognizes glyphs before segmentation ever runs. Observed on the
rendered page: `កម្ពុជា` (Cambodia) OCR'd as `កម្ពជា` (dropped the ុ vowel
sign), `ក្នុង` OCR'd as `ក្នង` (same), `ផ្លូវ` OCR'd as `ផ្លវ`, and
`ចោមចៅ` OCR'd as `បោមចៅ` (consonant substitution). Once a character is
wrong, no amount of exact-string matching in `protected_terms` will
recognize it — `segment()` only re-merges tokens that already spell the
correct term. This is a Tesseract/font/DPI recognition-quality issue, not a
segmentation issue, and is out of scope for this module; worth revisiting
separately (e.g. higher render DPI, a different PSM, or an OCR
post-correction pass) if OCR accuracy on real scans becomes a priority.

## Practical consequence for engine choice

- LibreOffice's engine gets Khmer line-breaking right **natively**, with or
  without the segmentation step.
- WeasyPrint gets it right **only if** text has passed through
  `process_text()` first (or already has real spaces).
- Justify quality still differs even after segmentation: LibreOffice/Word
  distributes stretch across many syllable-level points; WeasyPrint's CSS
  justify only stretches at literal space/ZWSP characters, which can still
  look uneven on a line with very few of them. This is the reasoning behind
  the two-engine, format-routed design in `doc_engine` — see
  `architecture.md`.
