import tempfile
import unittest
from pathlib import Path

from build import ClipEntry, Manifest, build, check, render


def manifest(*clips: ClipEntry) -> Manifest:
    return {
        "title": "Test <Board>",
        "voices": [{"id": "dap9000", "label": "DAP-9000", "description": "Synthetic."}],
        "clips": list(clips),
    }


class BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "clips" / "dap9000").mkdir(parents=True)
        (self.root / "clips" / "dap9000" / "hello.mp3").write_bytes(b"ID3")
        (self.root / "style.css").write_text("body {}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_valid_manifest_has_no_problems(self) -> None:
        good = manifest({"id": "hello", "label": "Hello", "voice": "dap9000", "file": "clips/dap9000/hello.mp3"})

        self.assertEqual(check(good, self.root), [])

    def test_check_reports_each_kind_of_problem(self) -> None:
        bad = manifest(
            {"id": "a", "label": "A", "voice": "dap9000", "file": "clips/dap9000/missing.mp3"},
            {"id": "a", "label": "B", "voice": "nobody", "file": "clips/dap9000/hello.mp3"},
            {"id": "c", "label": "C", "voice": "dap9000", "file": "build.py"},
            {"id": "d", "label": "", "voice": "dap9000", "file": "clips/dap9000/hello.mp3"},
        )

        problems = " ".join(check(bad, self.root))

        for expected in ("doesn't exist", "already used", "unknown voice", "into clips/", "missing label"):
            self.assertIn(expected, problems)

    def test_the_page_escapes_text_and_needs_no_javascript(self) -> None:
        page = render(
            manifest({"id": "hi", "label": "<Hi & bye>", "voice": "dap9000", "file": "clips/dap9000/hello.mp3"}),
            self.root,
        )

        self.assertIn("&lt;Hi &amp; bye&gt;", page)
        self.assertIn("Test &lt;Board&gt;", page)
        self.assertIn('<source src="clips/dap9000/hello.mp3" type="audio/mpeg">', page)
        self.assertIn("AI-generated", page)
        self.assertNotIn("<script", page)

    def test_the_page_only_loads_its_own_files_over_https(self) -> None:
        page = render(manifest(), self.root)

        self.assertIn("script-src 'none'", page)
        self.assertIn("default-src 'self'", page)
        self.assertIn("upgrade-insecure-requests", page)
        self.assertNotIn("http://", page)

    def test_an_empty_board_says_so(self) -> None:
        self.assertIn("No clips yet.", render(manifest(), self.root))

    def test_build_writes_the_page_styles_and_clips(self) -> None:
        site = self.root / "_site"

        build(
            manifest({"id": "hi", "label": "Hi", "voice": "dap9000", "file": "clips/dap9000/hello.mp3"}),
            self.root,
            site,
        )

        self.assertTrue((site / "index.html").is_file())
        self.assertTrue((site / "style.css").is_file())
        self.assertTrue((site / "clips" / "dap9000" / "hello.mp3").is_file())
        self.assertTrue((site / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
