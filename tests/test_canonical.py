from smelt.canonical import canonical_url, clean_input
from smelt.config import Config
from smelt.library import find_by_ref
from smelt.pipeline import run


def test_copy_paste_debris_is_stripped():
    assert clean_input("  (https://example.com/a)  ") == "https://example.com/a"
    assert clean_input("<https://example.com/a>,") == "https://example.com/a"
    assert clean_input("see https://example.com") == "see https://example.com"  # free text untouched


def test_a_timestamp_link_is_the_same_video():
    plain = "https://www.youtube.com/watch?v=abc123"
    stamped = "https://www.youtube.com/watch?v=abc123&t=78s"
    short = "https://youtu.be/abc123?si=xYz"
    assert canonical_url(plain) == canonical_url(stamped) == canonical_url(short)
    assert canonical_url(plain) == "https://youtube.com/watch?v=abc123"


def test_tracking_noise_is_dropped_but_real_params_survive():
    assert canonical_url("https://shop.example.com/p?p=123&utm_source=x&fbclid=y") == (
        "https://shop.example.com/p?p=123"
    )


def test_hosts_and_slashes_are_normalized():
    assert canonical_url("https://www.Example.com/a/") == "https://example.com/a"
    assert canonical_url("https://x.com/user/status/1") == "https://twitter.com/user/status/1"


def test_non_urls_are_left_alone():
    assert canonical_url("just some text") == "just some text"
    assert canonical_url("mailto:a@b.c") == "mailto:a@b.c"


def test_the_same_source_twice_is_one_note(tmp_path, monkeypatch):
    from smelt.adapters import webpage

    monkeypatch.setattr(
        "smelt.pipeline.extract_webpage",
        lambda url: webpage.Extracted(title="Fixed", text="an automation pipeline for agents", meta={}),
    )
    config = Config(staging_dir=tmp_path)

    first = run("url", ref="https://example.com/a?utm_source=x", config=config)
    second = run("url", ref="(https://www.example.com/a/)", config=config)  # same source, messy

    assert first.event.source.ref == "https://example.com/a"
    assert second.event.id == first.event.id  # re-read, not a duplicate
    assert find_by_ref("https://example.com/a", tmp_path) == first.event.id
