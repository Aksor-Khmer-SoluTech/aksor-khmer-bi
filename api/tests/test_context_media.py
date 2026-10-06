"""Unit tests for context_media.py's image_id -> image_bytes resolution
-- the one piece of the image-embedding feature that's unique to api/app
(doc_engine itself never sees an image_id, only already-resolved bytes;
see doc_engine.images' module docstring). Chart/image *rendering* itself
(the InlineImage step) is exercised at the doc_engine package level
(packages/doc_engine/tests/), same split the existing chart tests use.
"""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import image_store
from app.context_media import ImageResolutionError, resolve_image_refs
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _make_png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), (0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _create_image(org_id=ROOT_ORG_ID):
    return image_store.create_image(
        name="logo.png", content=_make_png_bytes(), org_id=org_id, folder_id=None, created_by=None
    )


def test_resolves_image_ref_to_bytes():
    image = _create_image()
    context = {"logo": {"image_id": image["id"], "width_mm": 30}}
    resolved = resolve_image_refs(context, ROOT_ORG_ID)
    assert resolved["logo"]["width_mm"] == 30
    assert resolved["logo"]["image_bytes"] == image_store.get_image_bytes(image["id"])


def test_resolves_nested_and_leaves_other_values_untouched():
    image = _create_image()
    context = {
        "customer_name": "Someone",
        "items": [{"label": "x"}, {"photo": {"image_id": image["id"]}}],
    }
    resolved = resolve_image_refs(context, ROOT_ORG_ID)
    assert resolved["customer_name"] == "Someone"
    assert resolved["items"][0] == {"label": "x"}
    assert "image_bytes" in resolved["items"][1]["photo"]


def test_unknown_image_id_raises():
    with pytest.raises(ImageResolutionError):
        resolve_image_refs({"logo": {"image_id": "does-not-exist"}}, ROOT_ORG_ID)


def test_cross_org_image_reference_rejected(auth_headers):
    other_org = client.post("/api/v1/organizations", json={"id": "otherorg", "name": "Other Org"}, headers=auth_headers)
    assert other_org.status_code == 200, other_org.text
    image = _create_image(org_id="otherorg")
    with pytest.raises(ImageResolutionError):
        resolve_image_refs({"logo": {"image_id": image["id"]}}, ROOT_ORG_ID)


def test_orgless_report_cannot_reference_any_image():
    image = _create_image()
    with pytest.raises(ImageResolutionError):
        resolve_image_refs({"logo": {"image_id": image["id"]}}, None)
