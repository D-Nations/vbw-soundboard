# Very Bad Robots

A soundboard of **AI-generated** voice clips imitating the hosts of the
[Very Bad Wizards](https://verybadwizards.com) podcast. Every clip was made with voice conversion
models. None of them were spoken by the people they sound like.

The site is plain HTML and CSS with the browser's built-in audio players, so it needs no JavaScript. It's served
over HTTPS, and its Content Security Policy only lets it load its own files, blocks scripts, and upgrades any
`http://` request to `https://`.

## Voices

| Voice | Imitates |
|---|---|
| DaveBot | Dave Pizarro |
| TamBot | Tamler Sommers |

## How it works

- The site is written as one Markdown file per tab in voice_swapper's `soundboard_staging/` folder.
  `python -m voice_service.export_soundboard` there encodes the clips into `clips/`, one folder per tab, writes
  `clips.json` and runs `build.py`.
- `clips.json` holds the site's title and its tabs. Each tab has an `id`, a `label` for the tab bar, an `intro` in
  Markdown, and its clips: an `id`, the `label` shown on the page, the `voices` heard in it, an optional `note` in
  Markdown, and its `file`.
- `build.py` checks the manifest (every file exists, is an audio file under `clips/`, and is under 2 MB) and
  writes the site to `_site/`: `index.html` for the first tab and `<tab id>.html` for the rest, each with the same tab
  bar and AI-generated notice. Intros and notes support a small, safe Markdown subset. It uses only the Python standard library.
- `.github/workflows/pages.yml` runs the tests and the build on every push and pull request. On `main` it pushes
  the built site to the `gh-pages` branch, which GitHub Pages publishes. Every step is a shell command, using
  `git` and [uv](https://docs.astral.sh/uv/), so nothing in the project runs on Node.

Clips are produced and exported by the [voice_swapper](https://github.com/D-Nations/voice_swapper) project,
which includes this repository as a submodule.

## Building locally

```
python build.py          # check the manifest and build _site/
python build.py --check  # only check
python -m unittest discover -s tests -t .
```
