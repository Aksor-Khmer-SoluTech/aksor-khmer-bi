# Khmer Protected Terms — Standard Procedure & Reference

This is the operating manual for `aksor_khmer_ocr_segmenter`'s protected-terms
system: what it is, the step-by-step procedure for adding a new entry (or
injecting/excluding one at runtime via a `.txt`/`.json` file instead of
editing code), the rubric for deciding whether a mis-split is worth
protecting, and the full current catalog by category. For the background
on *why* this exists (ICU's Khmer word breaker vs. WeasyPrint/Pango's lack
of one), see [`khmer-line-breaking.md`](khmer-line-breaking.md) — this doc
assumes that context and focuses on the procedure and the data.

## Quick reference

| Location | Purpose |
|---|---|
| `packages/aksor_khmer_ocr_segmenter/src/aksor_khmer_ocr_segmenter/protected_terms/` | Built-in term modules, one file per category |
| `protected_terms/__init__.py` | Concatenates every category module into `PROTECTED_TERMS` |
| `protected_terms/loader.py` | Loads *extra* terms to inject, and terms to exclude, from a user-supplied `.txt`/`.json` file or a directory of `.txt` files (env var or per-call) |
| `segmenter.py` | `segment()`/`insert_breaks()` — consumes `PROTECTED_TERMS` + injected terms, minus excluded terms |
| `tests/test_segmenter.py` | Parametrizes a regression test over every entry in `PROTECTED_TERMS` automatically |
| `tests/test_protected_terms_loader.py` | Tests the inject/exclude file mechanism (`.txt`, `.json`, env vars, per-call scoping) |
| `samples/protected_terms_example.txt` / `.json` | Example format for an injectable terms file |
| `samples/excluded_terms_example.txt` | Example format for an exclusion file |

**Current total: 106 built-in terms across 8 categories** (table below).

---

## Standard procedure: adding a new protected term

Follow these steps whenever you find (or suspect) ICU is mis-splitting a
word:

### 1. Reproduce it against raw ICU

Never add a term on guesswork — confirm the exact wrong split first:

```bash
cd /Users/siengsotheara/aksor-khmer-bi
source venv/bin/activate
python3 -c "
import icu
KM = icu.Locale('km')
def raw(text):
    bi = icu.BreakIterator.createWordInstance(KM)
    bi.setText(text)
    words, start = [], 0
    for end in bi:
        words.append(text[start:end]); start = end
    return words
print(raw('YOUR_CANDIDATE_WORD_HERE'))
"
```

If it returns a single-element list, ICU already handles it correctly —
nothing to do.

### 2. Classify the split (see rubric below)

- **Clear bug** → protect it.
- **Borderline** (splits at a real, independently valid word/suffix) →
  protect it anyway if the compound is common enough to matter in real
  documents, but mark it `# Borderline` with a one-line reason.
- **Not a bug** (a linguistically correct two-word split, e.g. splits at
  "and", or a generic administrative word + a proper name) → leave it
  alone. Don't add it.

### 3. Pick the right category file (or add a new one)

See the category table below. If nothing fits, create a new module
following the existing pattern (module docstring + `TERMS: tuple[str,
...]`), then register it in `protected_terms/__init__.py`'s import list and
concatenation.

### 4. Add the entry with a comment

Format: the term string, then a comment giving the gloss and the exact
wrong split observed:

```python
"ពោធិ៍សែនជ័យ",  # Porsenchey (Phnom Penh khan) -- splits into ['ពោធិ៍', 'សែន', 'ជ័យ']
```

### 5. Run the test suite

No new test file/function needed — `test_segmenter.py` parametrizes over
every entry in `PROTECTED_TERMS`, so your new entry is covered
automatically the moment it's added:

```bash
python3 -m pytest packages/aksor_khmer_ocr_segmenter/tests -q
```

### 6. One-off or project-specific term? Don't commit it — inject it instead

If the term is specific to one deployment/customer/dataset (a particular
company's own name, a specific staff member, a one-off local address) and
doesn't belong hard-coded into this open-source package, use the injectable
file mechanism instead of editing `protected_terms/`. It accepts either a
`.txt` file (one term per line, `#` comments allowed) or a `.json` file (an
array of strings, or `{"terms": [...]}`):

```bash
export AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE=/path/to/your_terms.txt
# or, scoped to one call:
aksor-khmer-ocr-segment --text "..." --protected-terms-file your_terms.txt
```

If you have (or expect to grow) more than one or two of these sources —
one file per customer, per branch, per dataset — point at a *directory*
instead: every `*.txt` file placed directly inside it is loaded and
merged, so adding a new exception list is "drop a file in," not "edit an
env var":

```bash
export AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR=/path/to/terms.d
# or, scoped to one call:
aksor-khmer-ocr-segment --text "..." --protected-terms-dir terms.d
```

Both mechanisms can be active at once (their terms simply merge); the
directory form only picks up `.txt` files, not `.json` — use the
single-file mechanism above if you need `.json`. See
`samples/protected_terms_example.txt` / `.json` for the file formats,
`api/khmer_protected_terms.d/README.md` for a worked directory example,
and `khmer-line-breaking.md`'s "Injecting (and excluding) extra terms from
a file" section for full details.

### 7. Built-in term wrong for your data? Exclude it — don't delete it

If a built-in entry turns out to be wrong or unwanted for a specific
project's text (e.g. it happens to collide with a genuinely different word
in that domain), don't remove it from the shared package — other users may
still need it. Use the symmetric exclude mechanism instead, same file
formats as injection:

```bash
export AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE=/path/to/your_exclusions.txt
# or, scoped to one call:
aksor-khmer-ocr-segment --text "..." --exclude-terms-file your_exclusions.txt
```

Same directory form as injection above, for when you have more than a
couple of exclusion sources:

```bash
export AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR=/path/to/exclude.d
# or, scoped to one call:
aksor-khmer-ocr-segment --text "..." --exclude-terms-dir exclude.d
```

See `samples/excluded_terms_example.txt` for the format. Exclusion applies
to built-in terms, env-injected terms, and terms from an inject file/directory
alike — if the same term is both injected and excluded in one call, exclusion
wins. This never modifies `PROTECTED_TERMS` itself; it's purely a per-run
override.

---

## Configuring terms from the portal (no code, no restart)

Steps 1–7 above are for the *built-in* catalog and the server's config files.
Day-to-day, terms are managed in the portal, in three layers that **add
together** (and "never protect" beats all of them):

| Layer | Where | Who | Applies to |
|---|---|---|---|
| Built-in list + the server's config files | code / mounted files (steps 1–7) | whoever deploys | every report, every organization — shown **read-only** under *Manage → Protected Terms → Deployment-wide list* (it is re-read from the files at each API restart, and its version bumps when they change) |
| **Shared sets** | *Manage → Protected Terms* → **+ New set** | needs the `protected_terms:manage` permission | any report in the organization that selects the set |
| **This report's own terms** | the report's **Protected Terms** tab (*Templates → the report*) | needs `report:manage` | that one report |

- **Sets are linked, not copied.** Editing a set updates every report that
  selects it on its next render; deleting one just stops a report getting its
  terms (the report keeps rendering).
- **Type a term and press Enter** — it becomes a pill; click a pill to edit it,
  `×` to remove it. Paste a list (one per line, e.g. a spreadsheet column) to add
  many at once. Spaces are part of a term (`ធនាគារ អេស៊ីលីដា` is one term), repeats
  are ignored, and a term still being typed when you click Save is kept. Up to
  1,000 terms of 200 characters each per list. The Manage page's search also looks
  *inside* sets, so you can check whether a name is already covered.
- **Never protect** hands a term back to the normal word-breaker. It wins over
  every layer, including the deployment-wide list, so a report can opt out of a
  term a set or the config files protect.
- Anyone who can manage reports can *see* the sets (to pick one); only
  `protected_terms:manage` can create, edit or delete them.

## Classification rubric

| Case | Action | Example |
|---|---|---|
| Fragments are individually meaningless (broken mid-syllable/mid-morpheme) | **Protect** | `ឥណ្ឌូនេស៊ី` → `ឥណ្ឌូ`/`នេ`/`ស៊ី` |
| Split lands on a real bound suffix/prefix (`ភាព`, `ដ្ឋាន`, `ព្រះរាជ-`) — each half is technically valid but the compound reads as one term in formal use | **Protect, flag as borderline** | `អធិបតេយ្យភាព` → `អធិ`/`បតេយ្យ`/`ភាព` |
| Split lands between two genuinely independent, commonly-standalone words (a conjunction, a generic administrative/geographic word + a proper name) | **Leave alone** | `ក្រសួងសេដ្ឋកិច្ចនិងហិរញ្ញវត្ថុ` → correctly splits at "and"; `កូរ៉េខាងត្បូង` → "Korea" + "South" |
| Already a single token | **No action** | `ភ្នំពេញ`, `អូស្ត្រាលី`, `ឥវ៉ាន់` |

When in doubt, lean toward *not* protecting — a false split is usually less
harmful than a false merge that hides a real word boundary the reader
needed.

---

## Full catalog by category

### `countries_places.py` — foreign country/city names (27 terms)

| Term | Gloss | Wrong split |
|---|---|---|
| ឥណ្ឌូនេស៊ី | Indonesia | ឥណ្ឌូ / នេ / ស៊ី |
| ប៊ុនថន | Bhutan | ប៊ុ / ន / ថន |
| ហូឡង់ | Netherlands | ហូ / ឡង់ |
| អារ៉ាប៊ីសាអូឌីត | Saudi Arabia | អា / រ៉ា / ប៊ី / សា / អូឌីត |
| កាតា | Qatar | កា / តា |
| ស៊ីង្ហបុរី | Singapore | ស៊ីង្ / ហបុ / រី |
| ម៉ីយ៉ាន់ម៉ា | Myanmar (alt) | ម៉ី / យ៉ាន់ / ម៉ា |
| ណេប៉ាល់ | Nepal | ណេ / ប៉ាល់ |
| បង់ក្លាដែស | Bangladesh | បង់ / ក្លា / ដែស |
| អាហ្គានីស្ថាន | Afghanistan | អាហ្ / គា / នី / ស្ថាន |
| ដិន្នឺម៉ាក | Denmark | ដិ / ន្នឺ / ម៉ាក |
| ប៊ែងកុក | Bangkok | ប៊ែង / កុក |
| ញូវយ៉ក | New York | ញូ / វយ៉ / ក |
| ប៊្រុចសែល | Brussels | ប៊្រុច / សែល |
| ស្លូវ៉េនី | Slovenia | ស្លូ / វ៉េ / នី |
| ក្រូអាស៊ី | Croatia | ក្រូ / អាស៊ី |
| សឺប៊ី | Serbia | សឺ / ប៊ី |
| ប៊ូស្នី | Bosnia | ប៊ូ / ស្នី |
| អ៊ូសបេគីស្ថាន | Uzbekistan | អ៊ូ / សបេ / គី / ស្ថាន |
| តាជីគីស្ថាន | Tajikistan | តាជី / គី / ស្ថាន |
| គូវ៉ែត | Kuwait | គូ / វ៉ែត |
| យេម៉ែន | Yemen | យេ / ម៉ែ / ន |
| ទុយនីស៊ី | Tunisia | ទុយ / នី / ស៊ី |
| ណីហ្សេរីយ៉ា | Nigeria | ណី / ហ្សេ / រី / យ៉ា |
| ហ្កាណា | Ghana | ហ្កា / ណា |
| ចាមេកា | Jamaica | ចា / មេ / កា |
| វេនេស៊ុយអេឡា | Venezuela | វេនេ / ស៊ុយ / អេ / ឡា |

*Note: all 21 Cambodian top-level provinces were tested and found already
correct — no protection needed at the province level. The problem is
concentrated in foreign country/city transliterations and, separately, in
domestic sub-provincial names (next section).*

### `khmer_places.py` — Cambodian domestic administrative/street names (6 terms)

Found via an end-to-end OCR round trip on a real property-tax address
field, not synthetic testing.

| Term | Gloss | Wrong split |
|---|---|---|
| ពោធិ៍សែនជ័យ | Porsenchey (Phnom Penh khan) | ពោធិ៍ / សែន / ជ័យ |
| ចបារអំពៅ | Chbar Ampov (Phnom Penh khan) | ចបា / រ / អំពៅ |
| ជ្រោយចង្វារ | Chroy Changvar (Phnom Penh khan) | ជ្រោយ / ចង្វា / រ |
| វេងស្រេង | Veng Sreng (major Phnom Penh boulevard) | វេ / ង / ស្រេង |
| ប្រាំពីរមករា *(borderline)* | 7 Makara (Phnom Penh khan; "seven"+"January") | ប្រាំពីរ / មករា |
| ពិភពថ្មី *(borderline)* | "New World" (common borey/development name; "world"+"new") | ពិភព / ថ្មី |

### `personal_names.py` — transliterated personal names (23 terms)

| Term | Gloss | Wrong split |
|---|---|---|
| ម៉ាយខល | Michael | ម៉ាយ / ខល |
| រ៉ូប៊ឺត | Robert | រ៉ូប៊ឺ / ត |
| វ៉ិលសុន | Wilson | វ៉ិល / សុន |
| ម៉ារី | Mary | ម៉ា / រី |
| អេលីសាបិត | Elizabeth | អេ / លី / សា / បិត |
| ដេវីឌ | David | ដេ / វី / ឌ |
| ចេនណាហ្វើ | Jennifer | ចេ / នណា / ហ្វើ |
| ស្មីធ | Smith | ស្មី / ធ |
| អាឡិចសាន់ឌឺ | Alexander | អា / ឡិច / សាន់ / ឌឺ |
| វ៉ាឡិនធីណា | Valentina | វ៉ា / ឡិន / ធី / ណា |
| គ្រីស្ទីណា | Christina | គ្រី / ស្ទី / ណា |
| ណាតាសា | Natasha | ណា / តា / សា |
| ចាក់សុន | Jackson | ចា / ក់ / សុន |
| ថូម៉ាស | Thomas | ថូ / ម៉ាស |
| វិល្លៀម | William | វិល្ / លៀម |
| ចេណេត | Janet | ចេ / ណេត |
| សាមានតា | Samantha | សា / មាន / តា |
| ណាតាលី | Natalie | ណា / តា / លី |
| អូលីវីយេ | Olivier | អូ / លី / វី / យេ |
| ដានីយែល | Daniel | ដា / នី / យែល |
| ចូសែប | Joseph | ចូ / សែប |
| ភីធើ | Peter | ភី / ធើ |
| ស្តេផានី | Stephanie | ស្តេ / ផា / នី |

### `native_personal_names.py` — native (non-transliterated) Khmer given names (10 terms)

**Scope note:** unlike the other categories, personal names are
combinatorially unbounded — this list is illustrative, not exhaustive.
Prefer a project-local injectable file (see the `api` project's
`khmer_protected_terms.txt` for a worked example) over adding a
one-off/deployment-specific name here.

| Term | Gloss | Wrong split |
|---|---|---|
| សុគន្ធា | Sokunthea | សុ / គន្ធា |
| ដារា | Dara | ដា / រា |
| ចន្ទនីរដ្ឋ | Chandaneth | ចន្ទ / នី / រដ្ឋ |
| សុវណ្ណដារា | Sovandara | សុវណ្ណ / ដា / រា |
| ធារ៉ា | Thara | ធា / រ៉ា |
| ចាន់ណារិទ្ធ | Channarith | ចាន់ / ណា / រិទ្ធ |
| សុផាត់ | Sopheak (variant) | សុ / ផាត់ |
| ណារិន | Narin | ណា / រិន |
| ចាន់ថា *(borderline)* | Chantha ("moon"+"to say") | ចាន់ / ថា |
| ស្រីនាង *(borderline)* | Sreynang ("girl"+"she") | ស្រី / នាង |

### `surnames.py` — transliterated Chinese/Vietnamese surnames (3 terms)

| Term | Gloss | Wrong split |
|---|---|---|
| ង៉ែម | Nguyen (variant) | ង៉ែ / ម |
| វ៉ាំង | Wang | វ៉ាំ / ង |
| ប៊ុយ | Bui | ប៊ុ / យ |

### `loanwords_science_tech.py` — science/technology loanwords (8 terms)

| Term | Gloss | Wrong split |
|---|---|---|
| តេឡេវិស្យុន | television | តេ / ឡេវិ / ស្យុន |
| រ៉ាឌីយូ | radio | រ៉ា / ឌី / យូ |
| អុកស៊ីសែន | oxygen | អុក / ស៊ី / សែន |
| អង់ទីប៊ីយោទិក | antibiotic | អង់ / ទី / ប៊ី / យោ / ទិ / ក |
| អាល្កុល | alcohol | អាល្ / កុល |
| អាំងស៊ុយលីន | insulin | អាំង / ស៊ុយ / លីន |
| អេឡិចត្រុង | electron | អេ / ឡិច / ត្រុ / ង |
| ម៉ាញ៉េស្យូម | magnesium | ម៉ា / ញ៉េស្យូម |

### `brands_orgs.py` — brand/product/organization names (22 terms)

| Term | Gloss | Wrong split |
|---|---|---|
| ហ្វេសប៊ុក | Facebook | ហ្វេ / សប៊ុ / ក |
| សាំសុង | Samsung | សាំ / សុង |
| តូយូតា | Toyota | តូ / យូ / តា |
| យូនីសេហ្វ | UNICEF | យូនី / សេ / ហ្វ |
| អាឌីដាស | Adidas | អា / ឌី / ដាស |
| ណៃគី | Nike | ណៃ / គី |
| ផាណាសូនិក | Panasonic | ផា / ណា / សូ / និក |
| សូនី | Sony | សូ / នី |
| អាលីបាបា | Alibaba | អា / លី / បា / បា |
| នេតហ្វ្លិច | Netflix | នេត / ហ្វ្ / លិច |
| យូធូប | YouTube | យូ / ធូប |
| ធ្វីតធឺ | Twitter | ធ្វី / ត / ធឺ |
| អ៊ីនស្តាក្រម | Instagram | អ៊ី / ន / ស្តា / ក្រម |
| ស្តាបាក់ | Starbucks | ស្តា / បាក់ |
| ខេអេហ្វស៊ី | KFC | ខេ / អេ / ហ្វ / ស៊ី |
| ម៉ាកដូណាល់ | McDonald's | ម៉ាក / ដូ / ណាល់ |
| ភីអិលស៊ី | "PLC" (very common Cambodian business-entity suffix) | ភី / អិ / ល / ស៊ី |
| អេស៊ីលីដា | ACLEDA Bank | អេ / ស៊ី / លីដា |
| កាណាឌីយ៉ា | Canadia Bank | កា / ណា / ឌី / យ៉ា |
| រ៉ូយ៉ាល់ | "Royal" (bank name component) | រ៉ូ / យ៉ា / ល់ |
| ជីបម៉ុង | Chip Mong (verified official Khmer rendering) | ជីប / ម៉ុង |
| សហពាណិជ្ជ | Union Commercial Bank (UCB) name component — from verified official name ធនាគារសហពាណិជ្ជ; scoped to just this part so "ធនាគារ" (bank) still splits off normally | សហ / ពាណិជ្ជ |

### `legal_formal.py` — legal/formal Pali-Sanskrit vocabulary (7 terms)

| Term | Gloss | Wrong split |
|---|---|---|
| ព្រះរាជក្រឹត្យ | royal decree | ព្រះរាជ / ក្រឹត្យ |
| លិខិតបទដ្ឋានគតិយុត្ត | legal instrument | លិខិត / បទដ្ឋាន / គតិ / យុត្ត |
| អធិបតេយ្យភាព | sovereignty | អធិ / បតេយ្យ / ភាព |
| អនុលោមភាព *(borderline)* | compliance | អនុលោម / ភាព |
| អគ្គនាយកដ្ឋាន *(borderline)* | general department | អគ្គនាយក / ដ្ឋាន |
| អគ្គលេខាធិការដ្ឋាន *(borderline)* | secretariat-general | អគ្គលេខាធិការ / ដ្ឋាន |
| នីតិបញ្ញត្តិ *(borderline)* | legislative | នីតិ / បញ្ញត្តិ |

---

## Worked example: project-scoped terms for `api`

Every string in a report's render payload that contains Khmer goes through
`aksor_khmer_ocr_segmenter.process_text()` (see
`doc_engine/segmentation.py`'s `segment_generic`) before rendering. When
preparing real-world terms for this project:

- Cross-checked a set of realistic report payloads (taxpayer/address
  fields, bank names, line-item labels) against the built-in catalog —
  all already covered, no new bugs there.
- Tested additional real Cambodian banks likely to appear in a free-text
  bank-list field and native Khmer given names likely to appear in a
  taxpayer/customer-name field — found genuine new bugs, added to the
  shared `brands_orgs.py` / new `native_personal_names.py`.
- **Verified via web search before adding**, rather than shipping guesses:
  several initially-plausible bank-name transliterations (ABA, HSBC, CIMB,
  ICBC, and others) turned out to be wrong to add, because those banks'
  real Khmer-language material keeps the brand name in Latin script inline
  (e.g. `ធនាគារ ABA`, not a phonetic Khmer spelling) — so there's no Khmer
  word for ICU to mis-split in the first place. Only entries with an
  independently confirmed real Khmer spelling were added (`ជីបម៉ុង`/Chip
  Mong, `សហពាណិជ្ជ`/UCB).
- For genuinely unbounded fields like these (personal names, a free-text
  bank list), created `api/khmer_protected_terms.txt` (inject) and
  `khmer_protected_terms.exclude.txt` (exclude) — empty scaffolds this
  deployment's team populates from real production data it actually
  observes, wired via `AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` /
  `AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE` (see `api/README.md`). This is
  the intended pattern for any project using this package: verified,
  broadly-reusable terms go in the shared package; project-specific or
  unverifiable ones go in a local injectable file instead.

---

## Testing

```bash
cd /Users/siengsotheara/aksor-khmer-bi
source venv/bin/activate
python3 -m pytest packages/aksor_khmer_ocr_segmenter/tests -q
```

- `test_segmenter.py::test_segment_merges_known_protected_transliterations`
  is parametrized over the *entire* `PROTECTED_TERMS` tuple — every entry
  in every category file above gets its own regression test automatically.
- `test_protected_terms_loader.py` covers the inject/exclude file and
  directory mechanisms separately: `.txt` and `.json` parsing (including
  malformed JSON), missing-file/missing-directory errors, multi-file and
  multi-directory merging (directory glob is sorted by filename), env-var
  pickup for `AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE`/`_DIR` and
  `AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE`/`_DIR`, that `extra_terms_file`/
  `extra_terms_dir`/`exclude_terms_file`/`exclude_terms_dir` are all
  scoped to one call and don't leak into others, and that exclusion wins
  when a term is both injected and excluded in the same call (file or
  directory sourced alike).

## Notes on scope

This list is deliberately **not** a general Khmer word dictionary and isn't
meant to become one — ICU's own dictionary already handles the vast
majority of native Khmer text correctly (see `khmer-line-breaking.md` for
why we didn't hand-build a dictionary in the first place). Every entry here
exists because it was concretely observed splitting incorrectly, pinned
with a reproducible ICU version, and given a regression test. Don't add
speculative entries "just in case" — verify first (step 1 of the procedure
above).

Observed against PyICU 2.16.2 / ICU4C 78.3. A different ICU/CLDR build
could fix some of these on its own, or introduce new ones — that's exactly
what the parametrized regression suite is for.
