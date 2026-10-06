"""Load extra protected terms, and terms to exclude, from plain-text or
JSON files at runtime.

Lets someone extend or trim the built-in protected-terms lists (see
protected_terms/__init__.py) without editing Python. Two independent
mechanisms, both accepting a `.txt` file (one term per line, blank lines
and lines starting with '#' ignored) or a `.json` file (a JSON array of
strings, or an object `{"terms": [...]}`) -- the format is picked by file
extension:

INJECT (add terms ICU should treat as unbreakable, on top of the built-ins):
  - AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE environment variable -- a file path (or
    several, os.pathsep-separated). Applies automatically to every
    segment()/insert_breaks()/process_text()/process_image() call and the
    CLI.
  - extra_terms_file=<path or list of paths> passed explicitly to those
    same functions, or --protected-terms-file on the CLI (repeatable), for
    a one-off addition scoped to that call.
  - AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR environment variable, or
    extra_terms_dir=/--protected-terms-dir -- a *directory* (or several,
    os.pathsep-separated) instead of individual files: every `*.txt` file
    directly inside it is loaded and merged, sorted by filename for
    determinism. Use this instead of listing files one by one once you
    have more than a couple of exception-term sources (e.g. one file per
    customer/dataset) -- drop a new `.txt` file into the directory and
    it's picked up without touching any env var or code.

EXCLUDE (remove specific terms -- built-in or injected -- from the merge
set, reverting ICU's original behavior for just those terms):
  - AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE environment variable, same path/format
    rules as above.
  - exclude_terms_file=<path or list of paths>, or --exclude-terms-file on
    the CLI (repeatable), scoped to one call.
  - AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR environment variable, or
    exclude_terms_dir=/--exclude-terms-dir -- same directory-of-`*.txt`-files
    mechanism as AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR, mirrored for exclusions.

Directory mode only picks up `.txt` files (not `.json`) -- it's meant for
"drop a plain list of terms in, one per line," the common case for
non-developers maintaining exception lists; use the explicit-file
mechanism above if you need `.json`. A configured directory that doesn't
exist raises FileNotFoundError (fail loud, same as a missing file); an
existing directory with no matching `.txt` files is not an error -- it's
a valid "no exceptions yet" state.

Example your_terms.txt:

    # Company names specific to our dataset
    អេស៊ីលីដា
    វឌ្ឍនៈ

Example your_terms.json:

    ["អេស៊ីលីដា", "វឌ្ឍនៈ"]

    or: {"terms": ["អេស៊ីលីដា", "វឌ្ឍនៈ"]}

Exclusion always wins over injection: if the same term appears in both an
inject source and an exclude source, it ends up excluded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

INJECT_ENV_VAR = "AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE"
EXCLUDE_ENV_VAR = "AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE"
INJECT_DIR_ENV_VAR = "AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR"
EXCLUDE_DIR_ENV_VAR = "AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR"

# Kept for backward compatibility with existing imports.
ENV_VAR = INJECT_ENV_VAR


def _parse_terms_text(text: str) -> tuple[str, ...]:
    """Plain-text format: one term per line, blank lines and '#' comment
    lines ignored, leading/trailing whitespace stripped.
    """
    terms = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return tuple(terms)


def _parse_terms_json(text: str, *, source: str) -> tuple[str, ...]:
    """JSON format: a top-level array of strings, or an object with a
    "terms" array.
    """
    data = json.loads(text)
    if isinstance(data, list):
        raw_terms = data
    elif isinstance(data, dict) and isinstance(data.get("terms"), list):
        raw_terms = data["terms"]
    else:
        raise ValueError(
            f"{source}: expected a JSON array of strings, or an object "
            'like {"terms": [...]}'
        )
    return tuple(str(term).strip() for term in raw_terms if str(term).strip())


def load_terms_file(path: str | Path) -> tuple[str, ...]:
    """Parse one terms file -- `.json` (a JSON array, or `{"terms": [...]}`)
    or plain text (one term per line, `#` comments allowed), picked by file
    extension. Used for both inject and exclude files; the two are just
    different lists of the same shape. Raises FileNotFoundError if `path`
    doesn't exist -- fail loudly rather than silently running without terms
    the caller expected to be active. Raises ValueError on malformed JSON
    content.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return _parse_terms_json(text, source=str(path))
    return _parse_terms_text(text)


def load_terms_from_paths(paths: str | Path | list[str | Path] | None) -> tuple[str, ...]:
    """Load and concatenate terms from one path, a list of paths, or None
    (returns an empty tuple).
    """
    if paths is None:
        return ()
    if isinstance(paths, (str, Path)):
        paths = [paths]
    terms: list[str] = []
    for path in paths:
        terms.extend(load_terms_file(path))
    return tuple(terms)


def load_terms_from_dir(dir_path: str | Path) -> tuple[str, ...]:
    """Load and concatenate every `*.txt` file directly inside `dir_path`
    (not recursive), sorted by filename for a deterministic merge order.

    Raises FileNotFoundError if `dir_path` itself doesn't exist or isn't a
    directory -- fail loudly rather than silently running without terms
    the caller expected, same as `load_terms_file` does for a missing
    file. A directory that exists but has no matching `.txt` files is
    valid (returns an empty tuple) -- that's "no exceptions yet," not a
    misconfiguration.
    """
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Not a directory: {dir_path}")
    terms: list[str] = []
    for path in sorted(dir_path.glob("*.txt")):
        terms.extend(load_terms_file(path))
    return tuple(terms)


def load_terms_from_dirs(
    dirs: str | Path | list[str | Path] | None,
) -> tuple[str, ...]:
    """Load and concatenate terms from every `*.txt` file in one directory,
    a list of directories, or None (returns an empty tuple).
    """
    if dirs is None:
        return ()
    if isinstance(dirs, (str, Path)):
        dirs = [dirs]
    terms: list[str] = []
    for dir_path in dirs:
        terms.extend(load_terms_from_dir(dir_path))
    return tuple(terms)


def _load_from_env(env_var: str) -> tuple[str, ...]:
    raw = os.environ.get(env_var)
    if not raw:
        return ()
    paths = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    return load_terms_from_paths(paths)


def _load_dirs_from_env(env_var: str) -> tuple[str, ...]:
    raw = os.environ.get(env_var)
    if not raw:
        return ()
    dirs = [d.strip() for d in raw.split(os.pathsep) if d.strip()]
    return load_terms_from_dirs(dirs)


def load_terms_from_env() -> tuple[str, ...]:
    """Load inject terms from every file path listed in the
    AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE environment variable
    (os.pathsep-separated). Returns an empty tuple if unset.
    """
    return _load_from_env(INJECT_ENV_VAR)


def load_terms_from_dirs_env() -> tuple[str, ...]:
    """Load inject terms from every `*.txt` file in every directory listed
    in the AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR environment variable
    (os.pathsep-separated). Returns an empty tuple if unset.
    """
    return _load_dirs_from_env(INJECT_DIR_ENV_VAR)


# Exclusion side of the same mechanism -- explicit names so call sites read
# clearly (`load_exclusions_from_env()` vs `load_terms_from_env()`).
load_exclusions_file = load_terms_file
load_exclusions_from_paths = load_terms_from_paths
load_exclusions_from_dir = load_terms_from_dir
load_exclusions_from_dirs = load_terms_from_dirs


def load_exclusions_from_env() -> tuple[str, ...]:
    """Load excluded terms from every file path listed in the
    AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE environment variable
    (os.pathsep-separated). Returns an empty tuple if unset.
    """
    return _load_from_env(EXCLUDE_ENV_VAR)


def load_exclusions_from_dirs_env() -> tuple[str, ...]:
    """Load excluded terms from every `*.txt` file in every directory
    listed in the AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR environment variable
    (os.pathsep-separated). Returns an empty tuple if unset.
    """
    return _load_dirs_from_env(EXCLUDE_DIR_ENV_VAR)
