from smelt.storage.naming import artifact_stem


def test_stem_is_filesystem_safe():
    stem = artifact_stem("2026-07-11", "youtube", "Wild/Title: with *chars*?", "https://x.y/z")
    assert "/" not in stem and "*" not in stem and "?" not in stem and ":" not in stem
    assert stem.startswith("2026-07-11-youtube-")


def test_stem_is_deterministic():
    a = artifact_stem("2026-07-11", "text", "Same", "ref")
    b = artifact_stem("2026-07-11", "text", "Same", "ref")
    assert a == b


def test_empty_title_gets_slug():
    stem = artifact_stem("2026-07-11", "text", "", "ref")
    assert "untitled" in stem
