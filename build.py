"""Build the soundboard's static site from clips.json, with no JavaScript.

Checks the manifest, then writes _site/ with index.html, the stylesheet and the clips. The GitHub Action
runs this on every push and deploys _site/ to GitHub Pages.

Run with: python build.py [--check]
"""

import argparse
import html
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "clips.json"
SITE = ROOT / "_site"
AUDIO_TYPES = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4"}
MAX_CLIP_BYTES = 2 * 1024 * 1024


class VoiceEntry(TypedDict):
    id: str
    label: str
    description: str


class ClipEntry(TypedDict):
    id: str
    label: str
    voice: str
    file: str


class Manifest(TypedDict):
    title: str
    voices: list[VoiceEntry]
    clips: list[ClipEntry]


@dataclass(frozen=True)
class Clip:
    id: str
    label: str
    voice: str
    path: Path

    @property
    def media_type(self) -> str:
        return AUDIO_TYPES[self.path.suffix.lower()]


def read_manifest(path: Path = MANIFEST) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} must hold a JSON object.")
    # check() reports anything the manifest is missing, so trust its shape from here.
    return cast(Manifest, data)


def check(manifest: Manifest, root: Path = ROOT) -> list[str]:
    """Everything wrong with the manifest and its files. Empty when the site can be built."""
    problems = []
    voices = {voice["id"] for voice in manifest["voices"]}
    seen: set[str] = set()
    for n, clip in enumerate(manifest["clips"], start=1):
        where = f"clip {n} ({clip.get('id', '?')})"
        missing = [key for key in ("id", "label", "voice", "file") if not clip.get(key)]
        if missing:
            problems.append(f"{where} is missing {', '.join(missing)}.")
            continue
        if clip["id"] in seen:
            problems.append(f"{where} has an id that's already used.")
        seen.add(clip["id"])
        if clip["voice"] not in voices:
            problems.append(f"{where} uses the unknown voice {clip['voice']!r}.")
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


def render(manifest: Manifest, root: Path = ROOT) -> str:
    """The page: one section per voice, one native audio player per clip."""
    esc = html.escape
    clips = [Clip(c["id"], c["label"], c["voice"], root / c["file"]) for c in manifest["clips"]]
    sections = []
    for voice in manifest["voices"]:
        mine = [clip for clip in clips if clip.voice == voice["id"]]
        if not mine:
            continue
        items = "\n".join(
            f'      <li id="{esc(clip.id)}">\n'
            f"        <p>{esc(clip.label)}</p>\n"
            f'        <audio controls preload="none"><source src="{esc(clip.path.relative_to(root).as_posix())}"'
            f' type="{clip.media_type}"></audio>\n'
            f"      </li>"
            for clip in mine
        )
        sections.append(
            f'  <section aria-labelledby="{esc(voice["id"])}-heading">\n'
            f'    <h2 id="{esc(voice["id"])}-heading">{esc(voice["label"])}</h2>\n'
            f'    <p class="voice">{esc(voice["description"])}</p>\n'
            f"    <ul>\n{items}\n    </ul>\n"
            f"  </section>"
        )
    body = "\n".join(sections) if sections else '  <p class="empty">No clips yet.</p>'
    title = esc(manifest["title"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>{title}</h1>
  <p class="notice"><strong>Every voice here is AI-generated.</strong> These are synthetic imitations made with
  voice conversion models. None of these recordings were spoken by the people they sound like.</p>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def build(manifest: Manifest, root: Path = ROOT, site: Path = SITE) -> None:
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    (site / "index.html").write_text(render(manifest, root), encoding="utf-8")
    shutil.copy(root / "style.css", site / "style.css")
    for clip in manifest["clips"]:
        target = site / clip["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(root / clip["file"], target)
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
        print(f"Built {len(manifest['clips'])} clips into {SITE.name}/")


if __name__ == "__main__":
    main()
