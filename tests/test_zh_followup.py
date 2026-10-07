"""Gemini-audit follow-up: source-strip names are translatable, starter chips send their English text, chips have Chinese."""
import re
from pathlib import Path

S = Path(__file__).resolve().parent.parent / "app" / "static"


def test_strip_name_is_its_own_text_node_so_colonless_keys_match():
    js = (S / "strip.js").read_text(encoding="utf8")
    assert '<span class="nm">' in js and "</span>: <span class=\"st\">" in js
    zh = (S / "i18n.js").read_text(encoding="utf8")
    assert '"Bitget order-book cache": ' in zh


def test_chips_keep_english_payload_and_have_chinese():
    home = (S / "home.js").read_text(encoding="utf8")
    assert 'data-q="${esc(c)}"' in home and "ask(b.dataset.q || b.textContent)" in home
    zh = (S / "i18n.js").read_text(encoding="utf8")
    chips = re.search(r"const CHIP_GROUPS = \[(.*?)\n\];", home, re.S).group(1)
    for q in re.findall(r'"([A-Z][^"]*\?)"', chips):
        assert f'"{q}": ' in zh, q
