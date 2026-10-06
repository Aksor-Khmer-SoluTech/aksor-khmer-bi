import json
from typing import Any

from pydantic import BaseModel, Field

# A setting's `code` -- lowercase, starts with a letter, then letters/
# digits/underscores/dots (dots for optional namespacing, e.g.
# "report.preview_layout"). Also applied to the URL path parameter in
# routers/users.py so a bad code 422s before touching the database.
SETTING_CODE_PATTERN = r"^[a-z][a-z0-9_.]{0,63}$"

# Settings are small UI preferences, not a document store -- capping the
# serialized size keeps one authenticated user from stuffing megabytes
# into the database through this generic endpoint.
MAX_SETTING_VALUE_BYTES = 16 * 1024


class UserSettingUpdate(BaseModel):
    value: Any = Field(
        ...,
        description="Any non-null JSON value (string, number, boolean, list or object), at most "
        f"{MAX_SETTING_VALUE_BYTES // 1024} KB serialized. DELETE the setting to clear it rather than storing null.",
    )


class UserSettingOut(BaseModel):
    code: str
    value: Any
    updated_at: str


def check_setting_value(value: Any) -> None:
    """Raises ValueError (with a message safe to show the caller) if
    `value` isn't storable as a setting.

    Run by the endpoint itself rather than as a pydantic validator on
    UserSettingUpdate on purpose: a failed pydantic validation echoes the
    offending input back inside FastAPI's 422 body, and a NaN/Infinity
    input can't be JSON-encoded there -- the caller would get a crashed
    500 instead of the 422 this is meant to produce.
    """
    if value is None:
        raise ValueError("value can't be null -- DELETE the setting to clear it")
    try:
        # allow_nan=False: NaN/Infinity parse fine from a request body but
        # aren't valid JSON, and PostgreSQL's JSON type rejects them at
        # insert time (SQLite would store one and then fail every read).
        encoded = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be valid JSON (NaN and Infinity aren't allowed)") from exc
    if len(encoded.encode("utf-8")) > MAX_SETTING_VALUE_BYTES:
        raise ValueError(f"value is larger than {MAX_SETTING_VALUE_BYTES // 1024} KB")
