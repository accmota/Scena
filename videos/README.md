# Videos

The YouTube channel's videos: every frame is drawn by a Scena program, and
everything here is what makes them. Git keeps what is written by hand, the
scripts and the texts; what they render can be rendered again and is
git-ignored.

| Folder | What | In git |
| --- | --- | --- |
| `scripts/` | The programs that draw the videos, one folder per video, and `kit/`, what they share | yes |
| `texts/` | Titles and descriptions, ready to paste: `channel.md` (the channel, the checklist before publishing), `footer.md` (the end of every description), `promo.md`, `buildups.md` | yes |
| `finals/` | The uploads: `promo/scena_<video>.mp4`, `buildups/buildup_<id>.mp4` and `.srt`, each with its thumbnail (`.jpg`); `channel/` (avatar, banner) | no |
| `recordings/` | What a video is made from: the takes (`<game>/<take>.mp4`, `tools/video/record_game.py`), the build-ups' steps (`buildup/<id>/`), each video's cue sheet, music cut and stills (`<video>/`), the ProRes masters (`masters.nosync/`) | no |

The texts are in English, with the Portuguese version YouTube Studio's
"Languages" tab asks for beside each one.

## Making a video

Each script's docstring ("Use") lists its commands, in order, from the
repository root. The usual steps:

1. `make_media.py` cuts the music from `examples/media/music/` into
   `recordings/<video>/`.
2. The takes the video shows: `python tools/video/record_game.py --take <game>/<take>`
   (the shot list is `tools/video/takes.py`).
3. `record_game.py` plays the video's program. A video that lays takes into
   its windows writes a ProRes master (`--prores`, into
   `recordings/masters.nosync/`) and a cue sheet; `kit/promo_composite.py`
   (or `kit/teaser_composite.py`, teasers 1 and 2 and the code video) lays the
   takes in. A video without takes renders its mp4 directly (`--crf 14`).
4. `kit/finish.py VIDEO.mp4 SERIES/NAME` makes it the upload in `finals/`:
   the picture as it is, the sound levelled to YouTube's -14 LUFS (raised
   with a limiter, or lowered). It consumes the video: one copy, the final.

A build-up: `python tools/video/buildup.py <id>`, then
`python videos/scripts/kit/finish.py videos/recordings/buildup/<id>.mp4 buildups/buildup_<id>`
(its `.srt` goes along). Balls takes `--keep-level`: its sound is only
effects, already peaking at -1 dB.

Thumbnails and the channel's art: `sh videos/scripts/channel/make_art.sh`
(stills from the finals; two takes of their own, recorded once).

## Masters

A ProRes master is 3 to 7 GB. It is kept only while its video is being
edited, so a composite can run again (a moved in-point, another take) without
rendering; delete it once the video is accepted. iCloud does not sync a folder
named `.nosync`, so a master is never uploaded there.

## Rendering again

The scripts render with the engine and the examples as they are. A game that
changed plays differently in its take, and a window's in-point may no longer
land on its moment: to make an old video again exactly, check out the commit it
was made from.

Each video folder (and `channel/`) has a `media` link to `examples/media`,
so a program names its art as an example does (`"fonts/Quantico-Bold.ttf"`).
On Windows the link needs git's `core.symlinks`.
