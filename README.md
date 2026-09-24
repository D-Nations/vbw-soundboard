# Very Bad Wizards Soundboard

A soundboard of **AI-generated** voice clips imitating the hosts of the
[Very Bad Wizards](https://verybadwizards.com) podcast. Every clip was made with voice conversion
models. None of them were spoken by the people they sound like.

The site is plain HTML and CSS with the browser's built-in audio players, so it needs no JavaScript.

## Voices

| Voice | Imitates |
|---|---|
| DAP-9000 | Dave Pizarro |
| Tamlerator | Tamler Sommers |

## How it works

- `clips/` holds the audio, one folder per voice.
- `clips.json` lists each voice and clip: an `id`, the `label` shown on the page, its `voice`, and its `file`.
- `build.py` checks the manifest (every file exists, is an audio file under `clips/`, and is under 2 MB) and
  writes the site to `_site/`. It uses only the Python standard library.
- `.github/workflows/pages.yml` runs the tests and the build on every push and pull request, and deploys to
  GitHub Pages from `main`.

Clips are produced and exported by the [voice_swapper](https://github.com/D-Nations/voice_swapper) project,
which includes this repository as a submodule.

## Building locally

```
python build.py          # check the manifest and build _site/
python build.py --check  # only check
python -m unittest discover -s tests -t .
```
