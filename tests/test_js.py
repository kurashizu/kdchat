"""The console is a static SvelteKit build (web/ -> ui/): it must be complete and must not use emoji."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "ui")


def test_ui_build_complete():
    html = open(os.path.join(UI, "index.html"), encoding="utf-8").read()
    refs = re.findall(r'"\./(_app/[^"]+)"', html)
    assert any(r.endswith(".js") for r in refs) and any(r.endswith(".css") for r in refs), refs
    for r in refs:
        assert os.path.isfile(os.path.join(UI, r)), r
    assert os.path.isfile(os.path.join(UI, "icon.svg"))


def test_ui_no_emoji():
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")
    for d, _, files in os.walk(os.path.join(ROOT, "web", "src")):
        for f in files:
            if f.endswith((".svelte", ".ts", ".html", ".css")):
                text = open(os.path.join(d, f), encoding="utf-8").read()
                assert not emoji.search(text), (f, emoji.search(text).group())
