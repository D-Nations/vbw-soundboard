import tempfile
import unittest
from pathlib import Path
from typing import cast

from build import ClipEntry, Manifest, SectionEntry, TabEntry, build, check, markdown, render


def clip(clip_id: str = "hello", **fields: object) -> ClipEntry:
    defaults = {"id": clip_id, "label": "Hello", "voices": ["DaveBot"], "note": "", "file": "clips/dap-9000/hello.mp3"}
    return cast(ClipEntry, defaults | fields)


def section(label: str, *clips: ClipEntry, intro: str = "") -> SectionEntry:
    return {"id": label.lower().replace(" ", "-"), "label": label, "intro": intro, "clips": list(clips)}


def tab(
    tab_id: str, *clips: ClipEntry, label: str = "", intro: str = "", sections: list[SectionEntry] | None = None
) -> TabEntry:
    """A tab with its clips in one unlabeled group, or with the given groups."""
    groups = sections if sections is not None else [section("", *clips)] if clips else []
    return {"id": tab_id, "label": label or tab_id.upper(), "intro": intro, "sections": groups}


def manifest(*tabs: TabEntry) -> Manifest:
    return {"title": "Test <Board>", "tabs": list(tabs) or [tab("home", label="Home")]}


class BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "clips" / "dap-9000").mkdir(parents=True)
        (self.root / "clips" / "dap-9000" / "hello.mp3").write_bytes(b"ID3")
        (self.root / "style.css").write_text("body {}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_valid_manifest_has_no_problems(self) -> None:
        good = manifest(tab("home", label="Home"), tab("dap-9000", clip()))

        self.assertEqual(check(good, self.root), [])

    def test_check_reports_each_kind_of_problem(self) -> None:
        bad = manifest(
            tab("home", label="Home"),
            tab(
                "dap-9000",
                clip("a", file="clips/dap-9000/missing.mp3"),
                clip("a"),
                clip("c", file="build.py"),
                clip("d", label=""),
            ),
            tab("dap-9000"),
            tab("Bad Id"),
        )

        problems = " ".join(check(bad, self.root))

        for expected in (
            "doesn't exist",
            "already used in this tab",
            "into clips/",
            "missing label",
            "id that's already used",
            "lowercase",
        ):
            self.assertIn(expected, problems)

    def test_each_tab_gets_a_page_with_the_tab_bar_and_notice(self) -> None:
        board = manifest(tab("home", label="Home", intro="Welcome."), tab("dap-9000", clip(), label="DAP-9000"))

        home = render(board, board["tabs"][0], self.root)
        dap = render(board, board["tabs"][1], self.root)

        for page in (home, dap):
            self.assertIn('<a href="index.html"', page)
            self.assertIn('<a href="dap-9000.html"', page)
            self.assertIn("AI-generated", page)
        self.assertIn('<a href="index.html" aria-current="page">Home</a>', home)
        self.assertIn('<a href="dap-9000.html" aria-current="page">DAP-9000</a>', dap)
        self.assertIn("<p>Welcome.</p>", home)
        self.assertIn("<h2>DAP-9000</h2>", dap)

    def test_clips_show_their_voices_note_and_player(self) -> None:
        board = manifest(tab("home"), tab("duo", clip(voices=["DaveBot", "TamBot"], note="From *2001*.")))

        page = render(board, board["tabs"][1], self.root)

        self.assertIn('<p class="credit">DaveBot &amp; TamBot</p>', page)
        self.assertIn("<em>2001</em>", page)
        self.assertIn('<source src="clips/dap-9000/hello.mp3" type="audio/mpeg">', page)

    def test_the_page_escapes_text_and_needs_no_javascript(self) -> None:
        board = manifest(tab("home"), tab("hi", clip(label="<Hi & bye>")))

        page = render(board, board["tabs"][1], self.root)

        self.assertIn("&lt;Hi &amp; bye&gt;", page)
        self.assertIn("Test &lt;Board&gt;", page)
        self.assertNotIn("<script", page)

    def test_the_page_only_loads_its_own_files_over_https(self) -> None:
        board = manifest()
        page = render(board, board["tabs"][0], self.root)

        self.assertIn("script-src 'none'", page)
        self.assertIn("default-src 'self'", page)
        self.assertIn("upgrade-insecure-requests", page)
        self.assertNotIn("http://", page)

    def test_markdown_keeps_only_safe_links_and_escapes_html(self) -> None:
        out = markdown("[ok](https://example.com) [no](javascript:alert(1)) <b>x</b>\n\n- one\n- **two**")

        self.assertIn('<a href="https://example.com">ok</a>', out)
        self.assertIn("[no](javascript:alert(1))", out)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", out)
        self.assertIn("<ul><li>one</li><li><strong>two</strong></li></ul>", out)

    def test_groups_get_headings_intros_and_links(self) -> None:
        board = manifest(
            tab(
                "home",
                label="Home",
                sections=[section("TAM-9000", clip("a"), intro="From *2001*."), section("Wizard Wars", clip("b"))],
            ),
        )

        page = render(board, board["tabs"][0], self.root)

        self.assertEqual(check(board, self.root), [])
        self.assertIn('<nav class="groups" aria-label="Groups">', page)
        self.assertIn('<a href="#tam-9000">TAM-9000</a>', page)
        self.assertIn('<h2 id="tam-9000">TAM-9000</h2>', page)
        self.assertIn('<h2 id="wizard-wars">Wizard Wars</h2>', page)
        self.assertIn("<em>2001</em>", page)
        self.assertLess(page.index('id="a"'), page.index('id="wizard-wars"'))

    def test_group_and_clip_ids_must_not_clash(self) -> None:
        bad = manifest(tab("home", sections=[section("Hello", clip("hello"))]))

        self.assertIn("already used in this tab", " ".join(check(bad, self.root)))

    def test_a_quiz_tab_asks_real_or_robot_and_marks_the_right_answer(self) -> None:
        board = manifest(
            tab("home"),
            tab("quiz", clip("q1", voices=[], answer="robot", note="**Robot:** TamBot."), clip("q2", answer="real")),
        )

        page = render(board, board["tabs"][1], self.root)

        self.assertEqual(check(board, self.root), [])
        self.assertIn('id="q1-real" value="real" class="wrong"', page)
        self.assertIn('id="q1-robot" value="robot" class="right"', page)
        self.assertIn('id="q2-real" value="real" class="right"', page)
        self.assertIn("<strong>Robot:</strong> TamBot.", page)
        self.assertIn('<button type="reset">', page)
        self.assertIn("out of 2 clips", page)
        self.assertIn("mixes real recordings", page)
        self.assertNotIn('class="credit"', page)
        self.assertNotIn("<script", page)

    def test_every_clip_in_a_quiz_needs_an_answer(self) -> None:
        bad = manifest(tab("home"), tab("quiz", clip("q1", answer="robot"), clip("q2"), clip("q3", answer="fake")))

        problems = check(bad, self.root)

        self.assertEqual(len(problems), 2)
        self.assertTrue(all("real or robot" in problem for problem in problems))

    def test_an_empty_tab_says_so(self) -> None:
        board = manifest(tab("home"), tab("empty"))

        self.assertIn("No clips yet.", render(board, board["tabs"][1], self.root))

    def test_build_writes_a_page_per_tab_with_styles_and_clips(self) -> None:
        site = self.root / "_site"

        build(manifest(tab("home", label="Home"), tab("dap-9000", clip())), self.root, site)

        self.assertTrue((site / "index.html").is_file())
        self.assertTrue((site / "dap-9000.html").is_file())
        self.assertTrue((site / "style.css").is_file())
        self.assertTrue((site / "clips" / "dap-9000" / "hello.mp3").is_file())
        self.assertTrue((site / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
