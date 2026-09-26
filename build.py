"""Build the soundboard's static site from clips.json, with no JavaScript.

clips.json holds the site's title and its tabs. Each tab has a label, an intro written in a small subset of
Markdown, and its clips. The first tab becomes index.html and every other tab <id>.html, each page with the
same tab bar and the same AI-generated notice, which isn't part of the editable text so it can't be dropped.

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
from typing import TypedDict, cast

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


class ClipEntry(TypedDict):
    id: str
    label: str
    voices: list[str]  # Voice names as shown, like DaveBot.
    note: str  # Markdown, may be empty.
    file: str


class TabEntry(TypedDict):
    id: str
    label: str
    intro: str  # Markdown, may be empty.
    clips: list[ClipEntry]


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
        clip_ids: set[str] = set()
        for n, clip in enumerate(tab.get("clips", []), start=1):
            where = f"{where_tab}, clip {n} ({clip.get('id', '?')})"
            missing = [key for key in ("id", "label", "voices", "file") if not clip.get(key)]
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
                problems.append(f"{where} is a {path.suffix or 'extensionless'} file, not one of {', '.join(AUDIO_TYPES)}.")
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


def render(manifest: Manifest, tab: TabEntry, root: Path = ROOT) -> str:
    """One tab's page: the title, the notice, the tab bar, the tab's intro and one native player per clip."""
    esc = html.escape
    title = esc(manifest["title"])
    nav = "\n".join(
        f'    <a href="{page_name(manifest, other)}"{" aria-current=\"page\"" if other is tab else ""}>'
        f"{esc(other['label'])}</a>"
        for other in manifest["tabs"]
    )
    items = "\n".join(
        f'    <li id="{esc(clip["id"])}">\n'
        f"      <p>{esc(clip['label'])}</p>\n"
        f'      <p class="credit">{esc(" & ".join(clip["voices"]))}</p>\n'
        + (f'      <div class="note">{markdown(clip["note"])}</div>\n' if clip.get("note") else "")
        + f'      <audio controls preload="none"><source src="{esc(Path(clip["file"]).as_posix())}"'
        f' type="{AUDIO_TYPES[Path(clip["file"]).suffix.lower()]}"></audio>\n'
        f"    </li>"
        for clip in tab["clips"]
    )
    home = tab is manifest["tabs"][0]
    heading = "" if home else f"  <h2>{esc(tab['label'])}</h2>\n"
    intro = f'  <div class="intro">\n{markdown(tab["intro"])}\n  </div>\n' if tab.get("intro") else ""
    clips = f"  <ul class=\"clips\">\n{items}\n  </ul>\n" if tab["clips"] else ("" if home else '  <p class="empty">No clips yet.</p>\n')
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
  <p class="notice"><strong>Every voice here is AI-generated.</strong> These are synthetic imitations made with
  voice conversion models. None of these recordings were spoken by the people they sound like.</p>
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
        for clip in tab["clips"]:
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
        clips = sum(len(tab["clips"]) for tab in manifest["tabs"])
        print(f"Built {len(manifest['tabs'])} tabs with {clips} clips into {SITE.name}/")


if __name__ == "__main__":
    main()
