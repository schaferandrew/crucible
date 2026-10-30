"""The README documents the command."""
import re

from support import ROOT


class TestReadme:
    """readme"""

    def test_has_a_command_example(self):
        readme = ROOT / "README.md"
        assert readme.is_file(), "no README.md"
        text = readme.read_text(encoding="utf-8", errors="replace")
        assert re.search(r"python3?\s+-m\s+interest\b[^\n]*--principal", text), \
            "no example command like `python -m interest --principal ...`"
