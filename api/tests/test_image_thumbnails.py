"""GET /api/v1/images/{id}/thumbnail -- the portal's card previews (app/image_store.get_thumbnail): a large picture
scaled to fit the box and kept, a small one sent as it is, the same visibility rule as the full file, and a
browser cache that a replaced picture can't fool."""
from io import BytesIO

from PIL import Image

from app import image_store
from tests.test_images import _create_folder, _make_png_bytes, _upload_image, client


def _noisy_png(size=(1600, 900)) -> bytes:
    """A large picture that doesn't compress to nothing (so it's well over the pass-through size)."""
    img = Image.effect_noise(size, 64).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_a_large_picture_is_scaled_to_fit_and_kept(auth_headers):
    original = _noisy_png()
    image = _upload_image(auth_headers, content=original).json()
    resp = client.get(f"/api/v1/images/{image['id']}/thumbnail?size=480", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(resp.content)) as thumb:
        assert thumb.size == (480, 270)  # fits 480 x 480, proportions kept
    assert len(resp.content) < len(original) / 4
    assert "private" in resp.headers["cache-control"] and resp.headers["etag"]
    # Made once: the second ask is served from the stored file.
    stored = list(image_store._image_dir(image["id"]).glob("thumb-*-480.webp"))
    assert len(stored) == 1
    again = client.get(f"/api/v1/images/{image['id']}/thumbnail?size=480", headers=auth_headers)
    assert again.content == resp.content


def test_a_small_picture_is_sent_as_it_is(auth_headers):
    content = _make_png_bytes(size=(64, 32))
    image = _upload_image(auth_headers, content=content).json()
    resp = client.get(f"/api/v1/images/{image['id']}/thumbnail", headers=auth_headers)
    assert resp.status_code == 200 and resp.content == content and resp.headers["content-type"] == "image/png"


def test_an_unchanged_picture_is_a_304_and_a_replaced_one_is_new(auth_headers):
    image = _upload_image(auth_headers, content=_noisy_png()).json()
    first = client.get(f"/api/v1/images/{image['id']}/thumbnail?size=240", headers=auth_headers)
    etag = first.headers["etag"]
    cached = client.get(f"/api/v1/images/{image['id']}/thumbnail?size=240", headers={**auth_headers, "If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b""

    replaced = client.put(
        f"/api/v1/images/{image['id']}/file",
        files={"file": ("new.png", _noisy_png((900, 1600)), "image/png")},
        headers=auth_headers,
    )
    assert replaced.status_code == 200, replaced.text
    fresh = client.get(f"/api/v1/images/{image['id']}/thumbnail?size=240", headers={**auth_headers, "If-None-Match": etag})
    assert fresh.status_code == 200 and fresh.headers["etag"] != etag
    with Image.open(BytesIO(fresh.content)) as thumb:
        assert thumb.size == (135, 240)  # the new, portrait picture
    # The thumbnail of the old picture is gone, not left beside the new one.
    assert len(list(image_store._image_dir(image["id"]).glob("thumb-*-240.webp"))) == 1


def test_only_the_offered_sizes(auth_headers):
    image = _upload_image(auth_headers).json()
    resp = client.get(f"/api/v1/images/{image['id']}/thumbnail?size=5000", headers=auth_headers)
    assert resp.status_code == 400


def test_a_thumbnail_is_as_private_as_the_picture(auth_headers, make_local_user):
    folder = _create_folder(auth_headers, "Private logos")
    image = _upload_image(auth_headers, folder_id=folder["id"]).json()
    _, outsider = make_local_user("thumb_outsider", "pw12345", role_names=())
    assert client.get(f"/api/v1/images/{image['id']}/thumbnail", headers=outsider).status_code == 404
    assert client.get("/api/v1/images/nope/thumbnail", headers=auth_headers).status_code == 404
