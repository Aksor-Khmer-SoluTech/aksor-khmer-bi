# Samples

Drop test images here (scanned forms, screenshots of unspaced Khmer text,
etc.) to try the OCR pipeline against real input:

```bash
aksor-khmer-ocr-segment --image samples/your_scan.png
```

## Protected-terms config examples

Two independent mechanisms, both accepting a `.txt` file (one term per
line, `#` comments allowed) or a `.json` file (an array of strings, or
`{"terms": [...]}`) — see `docs/protected-terms-guide.md` in the parent
repo for the full procedure:

- `protected_terms_example.txt` / `protected_terms_example.json` — **add**
  extra terms ICU should treat as unbreakable, on top of the built-ins:

  ```bash
  aksor-khmer-ocr-segment --image samples/your_scan.png \
      --protected-terms-file samples/protected_terms_example.txt
  ```

- `excluded_terms_example.txt` — **remove** a term (built-in or injected)
  from the merge set, reverting to ICU's original behavior for it:

  ```bash
  aksor-khmer-ocr-segment --image samples/your_scan.png \
      --exclude-terms-file samples/excluded_terms_example.txt
  ```

Both flags are repeatable, and both have an environment-variable
equivalent (`AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` /
`AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE`) that applies automatically without the
flag.
