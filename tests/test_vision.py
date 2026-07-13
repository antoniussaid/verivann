from smelt.adapters.gallery import is_gallery_url
from smelt.adapters.vision import video_onscreen_text, visual_enabled


def test_is_gallery_url():
    assert is_gallery_url("https://www.pinterest.com/pin/123/")
    assert is_gallery_url("https://example.com/photo.JPG")
    assert not is_gallery_url("https://example.com/article")


def test_visual_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SMELT_VISUAL", raising=False)
    assert visual_enabled() is False
    assert video_onscreen_text("https://x/y", tmp_path) == ""
