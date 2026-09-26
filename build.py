"""Build the soundboard's static site from clips.json, with no JavaScript.

clips.json holds the site's title and its tabs. Each tab has a label, an intro written in a small subset of
Markdown, and its groups of clips. The first tab becomes index.html and every other tab <id>.html, each page with the
same tab bar and the same AI-generated notice, which isn't part of the editable text so it can't be dropped.
A tab's clips come in groups, each shown under its own heading, with links to them at the top of the page.

A tab whose clips have answers ("real" or "robot") is a quiz. Its page asks which each clip is with a pair of
radio buttons, and plain CSS reveals the answer and keeps a running score, so it still needs no JavaScript.
Its notice says it mixes real recordings with AI-generated ones.

Checks the manifest, then writes _site/ with the pages, the stylesheet and the clips. The GitHub Action runs
this on every push and deploys _site/ to GitHub Pages.

Run with: python build.py [--check]
"""

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import NotRequired, TypedDict, cast

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "clips.json"
SITE = ROOT / "_site"
AUDIO_TYPES = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4"}
MAX_CLIP_BYTES = 2 * 1024 * 1024
# Only this site's own files load, never scripts, and any http:// request is upgraded to https://.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    "upgrade-insecure-requests"
)
TAB_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ANSWERS = ("real", "robot")


class ClipEntry(TypedDict):
    id: str
    label: str
    voices: list[str]  # Voice names as shown, like DaveBot.
    note: str  # Markdown, may be empty. On a quiz, shown once the clip is answered.
    file: str
    answer: NotRequired[str]  # Only on a quiz tab's clips: real or robot.


class SectionEntry(TypedDict):
    id: str  # Empty when label is.
    label: str  # A group's heading. Empty for clips shown without one.
    intro: str  # Markdown, may be empty.
    clips: list[ClipEntry]


class TabEntry(TypedDict):
    id: str
    label: str
    intro: str  # Markdown, may be empty.
    sections: list[SectionEntry]


class Manifest(TypedDict):
    title: str
    tabs: list[TabEntry]


def read_manifest(path: Path = MANIFEST) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} must hold a JSON object.")
    # check() reports anything the manifest is missing, so trust its shape from here.
    return cast(Manifest, data)


def page_name(manifest: Manifest, tab: TabEntry) -> str:
    """The first tab is the home page. The rest are named after their ids."""
    return "index.html" if tab is manifest["tabs"][0] else f"{tab['id']}.html"


def tab_clips(tab: TabEntry) -> list[ClipEntry]:
    return [clip for section in tab.get("sections", []) for clip in section.get("clips", [])]


def is_quiz(tab: TabEntry) -> bool:
    """A tab whose clips have answers asks which are real and which are robots."""
    return any("answer" in clip for clip in tab_clips(tab))


def check(manifest: Manifest, root: Path = ROOT) -> list[str]:
    """Everything wrong with the manifest and its files. Empty when the site can be built."""
    problems = []
    if not manifest.get("title"):
        problems.append("The site has no title.")
    if not manifest.get("tabs"):
        problems.append("The site has no tabs.")
    tab_ids: set[str] = set()
    for t, tab in enumerate(manifest.get("tabs", []), start=1):
        where_tab = f"tab {t} ({tab.get('id', '?')})"
        if not tab.get("id") or not tab.get("label"):
            problems.append(f"{where_tab} needs an id and a label.")
            continue
        if not TAB_ID.match(tab["id"]) or tab["id"] == "index":
            problems.append(f"{where_tab} needs an id of lowercase letters, digits and dashes, other than index.")
        if tab["id"] in tab_ids:
            problems.append(f"{where_tab} has an id that's already used.")
        tab_ids.add(tab["id"])
        # Groups and clips become ids on the same page, so they share one set.
        clip_ids: set[str] = set()
        for section in tab.get("sections", []):
            if section.get("label") and not section.get("id"):
                problems.append(f"{where_tab}, group {section['label']!r} needs an id.")
            elif section.get("id"):
                if section["id"] in clip_ids:
                    problems.append(f"{where_tab}, group {section['id']!r} has an id that's already used in this tab.")
                clip_ids.add(section["id"])
        quiz = is_quiz(tab)
        for n, clip in enumerate(tab_clips(tab), start=1):
            where = f"{where_tab}, clip {n} ({clip.get('id', '?')})"
            if quiz and clip.get("answer") not in ANSWERS:
                problems.append(f"{where} needs an answer of real or robot, like the tab's other clips.")
            required = ("id", "label", "file") if quiz else ("id", "label", "voices", "file")
            missing = [key for key in required if not clip.get(key)]
            if missing:
                problems.append(f"{where} is missing {', '.join(missing)}.")
                continue
            if clip["id"] in clip_ids:
                problems.append(f"{where} has an id that's already used in this tab.")
            clip_ids.add(clip["id"])
            path = root / clip["file"]
            if not path.resolve().is_relative_to((root / "clips").resolve()):
                problems.append(f"{where} must point into clips/.")
            elif path.suffix.lower() not in AUDIO_TYPES:
                problems.append(
                    f"{where} is a {path.suffix or 'extensionless'} file, not one of {', '.join(AUDIO_TYPES)}."
                )
            elif not path.is_file():
                problems.append(f"{where} points to {clip['file']}, which doesn't exist.")
            elif path.stat().st_size > MAX_CLIP_BYTES:
                problems.append(
                    f"{where} is {path.stat().st_size / 1e6:.1f} MB, over the {MAX_CLIP_BYTES / 1e6:.0f} MB limit."
                )
    return problems


# ---------------------------------------------------------------- markdown


def inline_markdown(text: str) -> str:
    """Escape text, then turn `code`, **bold**, *italics* and [links](https://...) into HTML.

    Links must be https:// or relative. Anything else stays as plain text.
    """
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", out)

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), html.unescape(match.group(2))
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url) and not url.startswith("https://"):
            return match.group(0)
        return f'<a href="{html.escape(url)}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, out)


def markdown(text: str) -> str:
    """A small, safe Markdown subset: paragraphs, - bullet lists and ### subheadings, with inline markup."""
    blocks = []
    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        if all(re.match(r"^[-*] ", line) for line in lines):
            items = "".join(f"<li>{inline_markdown(line[2:])}</li>" for line in lines)
            blocks.append(f"<ul>{items}</ul>")
        elif len(lines) == 1 and lines[0].startswith("### "):
            blocks.append(f"<h3>{inline_markdown(lines[0][4:])}</h3>")
        else:
            blocks.append(f"<p>{inline_markdown(' '.join(lines))}</p>")
    return "\n".join(blocks)


# ---------------------------------------------------------------- pages


NOTICE = (
    "<strong>Every voice here is AI-generated.</strong> These are synthetic imitations made with\n"
    "  voice conversion models. None of these recordings were spoken by the people they sound like."
)
QUIZ_NOTICE = (
    "<strong>This quiz mixes real recordings with AI-generated ones.</strong> Some clips are the hosts\n"
    "  themselves, and some are imitations made with voice conversion models. Each answer says which."
)


def audio_tag(clip: ClipEntry) -> str:
    file = Path(clip["file"])
    return (
        f'<audio controls preload="none"><source src="{html.escape(file.as_posix())}"'
        f' type="{AUDIO_TYPES[file.suffix.lower()]}"></audio>'
    )


def render_clip(clip: ClipEntry) -> str:
    esc = html.escape
    return (
        f'    <li id="{esc(clip["id"])}">\n'
        f"      <p>{esc(clip['label'])}</p>\n"
        f'      <p class="credit">{esc(" & ".join(clip["voices"]))}</p>\n'
        + (f'      <div class="note">{markdown(clip["note"])}</div>\n' if clip.get("note") else "")
        + f"      {audio_tag(clip)}\n"
        "    </li>"
    )


def render_quiz(tab: TabEntry) -> str:
    """Each clip with Real and Robot radio buttons, then a running score.

    Each button is marked right or wrong. style.css shows the matching verdict and the clip's note once one is
    picked, and counts the picked buttons with CSS counters for the score. Start over resets the form.
    """
    esc = html.escape
    questions = []
    for clip in tab_clips(tab):
        clip_id = esc(clip["id"])
        buttons = "".join(
            f'\n        <input type="radio" name="{clip_id}" id="{clip_id}-{answer}" value="{answer}"'
            f' class="{"right" if answer == clip.get("answer") else "wrong"}">'
            f'<label for="{clip_id}-{answer}">{answer.capitalize()}</label>'
            for answer in ANSWERS
        )
        note = markdown(clip["note"]) if clip.get("note") else ""
        questions.append(
            f'    <li id="{clip_id}">\n'
            f"      <p>{esc(clip['label'])}</p>\n"
            f"      {audio_tag(clip)}\n"
            f"      <fieldset>\n        <legend>Real or robot?</legend>{buttons}\n"
            f'        <div class="verdict"><p class="if-right">Right!</p><p class="if-wrong">Wrong.</p>{note}</div>\n'
            "      </fieldset>\n"
            "    </li>"
        )
    items = "\n".join(questions)
    return (
        '  <form class="quiz" autocomplete="off">\n'
        f'  <ol class="clips questions">\n{items}\n  </ol>\n'
        f'  <div class="score"><p class="tally">Your score: </p><p class="total">'
        f"out of {len(tab_clips(tab))} clips</p>"
        '<button type="reset">Start over</button></div>\n'
        "  </form>\n"
    )


def render_sections(tab: TabEntry, level: int) -> str:
    """Each group's heading, intro and clips, after a list of links to the groups when there's more than one.

    level is the headings' level: 2 on the home page, which has no tab heading, and 3 under a tab's heading.
    """
    esc = html.escape
    named = [section for section in tab["sections"] if section["label"]]
    parts = []
    if len(named) > 1:
        links = "\n".join(f'    <a href="#{esc(s["id"])}">{esc(s["label"])}</a>' for s in named)
        parts.append(f'  <nav class="groups" aria-label="Groups">\n{links}\n  </nav>\n')
    for section in tab["sections"]:
        if not section["clips"]:
            continue
        if section["label"]:
            parts.append(f'  <h{level} id="{esc(section["id"])}">{esc(section["label"])}</h{level}>\n')
        if section.get("intro"):
            parts.append(f'  <div class="intro">\n{markdown(section["intro"])}\n  </div>\n')
        items = "\n".join(render_clip(clip) for clip in section["clips"])
        parts.append(f'  <ul class="clips">\n{items}\n  </ul>\n')
    return "".join(parts)


def render(manifest: Manifest, tab: TabEntry, root: Path = ROOT) -> str:
    """One tab's page: the title, the notice, the tab bar, the tab's intro and one native player per clip."""
    esc = html.escape
    title = esc(manifest["title"])
    nav = "\n".join(
        f'    <a href="{page_name(manifest, other)}"{' aria-current="page"' if other is tab else ""}>'
        f"{esc(other['label'])}</a>"
        for other in manifest["tabs"]
    )
    home = tab is manifest["tabs"][0]
    heading = "" if home else f"  <h2>{esc(tab['label'])}</h2>\n"
    intro = f'  <div class="intro">\n{markdown(tab["intro"])}\n  </div>\n' if tab.get("intro") else ""
    if is_quiz(tab):
        clips = render_quiz(tab)
    elif tab_clips(tab):
        clips = render_sections(tab, level=2 if home else 3)
    else:
        clips = "" if home else '  <p class="empty">No clips yet.</p>\n'
    notice = QUIZ_NOTICE if is_quiz(tab) else NOTICE
    page_title = title if home else f"{esc(tab['label'])} · {title}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">
  <meta name="referrer" content="no-referrer">
  <title>{page_title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1><a href="index.html">{title}</a></h1>
  <p class="notice">{notice}</p>
  <nav aria-label="Tabs">
{nav}
  </nav>
</header>
<main>
{heading}{intro}{clips}</main>
</body>
</html>
"""


def build(manifest: Manifest, root: Path = ROOT, site: Path = SITE) -> None:
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for tab in manifest["tabs"]:
        (site / page_name(manifest, tab)).write_text(render(manifest, tab, root), encoding="utf-8")
        for clip in tab_clips(tab):
            target = site / clip["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(root / clip["file"], target)
    shutil.copy(root / "style.css", site / "style.css")
    # Tell GitHub Pages to serve the files as they are, without Jekyll.
    (site / ".nojekyll").touch()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Only check the manifest and its files")
    args = parser.parse_args(argv)

    manifest = read_manifest()
    problems = check(manifest)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    if not args.check:
        build(manifest)
        clips = sum(len(tab_clips(tab)) for tab in manifest["tabs"])
        print(f"Built {len(manifest['tabs'])} tabs with {clips} clips into {SITE.name}/")


if __name__ == "__main__":
    main()
