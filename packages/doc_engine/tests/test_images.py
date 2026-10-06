from doc_engine.images import is_image_spec


def test_is_image_spec_true_for_resolved_image_bytes():
    assert is_image_spec({"image_bytes": b"\x89PNG\r\n\x1a\n"})
    assert is_image_spec({"image_bytes": bytearray(b"fake"), "width_mm": 40})


def test_is_image_spec_false_for_unresolved_or_non_image_dicts():
    # The caller-facing spec shape (image_id, not yet resolved to bytes)
    # is never something doc_engine itself should treat as an image --
    # resolution happens one layer up, in api/app/context_media.py.
    assert not is_image_spec({"image_id": "abc123"})
    assert not is_image_spec({"label": "not an image"})
    assert not is_image_spec({"image_bytes": "not-bytes-a-plain-string"})
    assert not is_image_spec("image_bytes")
    assert not is_image_spec(["image_bytes"])
    assert not is_image_spec(None)
