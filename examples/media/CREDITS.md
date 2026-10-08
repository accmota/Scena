# Media credits and licenses

The images and sounds in `examples/media/` are **not** under Scena's MIT
license (`LICENSE` at the repository root covers the code and docs only).
Each folder keeps the original license notice of its files. This file lists
them all in one place.

> **Using these files in your own game?** Almost everything here is CC0: use
> it freely, with no permission or credit needed. The files under
> [Attribution required](#attribution-required) are different: if your game
> uses one of them, copy its credit into the game's credits screen or into the
> README you ship with the game. If you **modify** a CC-BY-SA sound, the
> modified version must be released under CC-BY-SA 3.0.

## Attribution required

Shipping a game (or anything else) that contains one of these files? Copy its
credit block into your game's credits screen or into the README / credits
file you distribute with it. If you change the file, say so (e.g. "trimmed,
converted to OGG").

### `audio/laser4.wav`, `audio/laser7.wav`: CC-BY 3.0

```
"Laser Fire" by dklon
https://opengameart.org/content/laser-fire
Licensed under CC BY 3.0: https://creativecommons.org/licenses/by/3.0/
```

### `audio/explosion01.wav`, `audio/explosion03.wav`, `audio/explosion07.wav`, `audio/explosion09.wav`: CC-BY-SA 3.0

```
"9 explosion sounds" by Unnamed (Viktor.Hahn@web.de)
https://opengameart.org/content/9-explosion-sounds
Licensed under CC BY-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/
```

Share-Alike applies to the sound itself: a modified version of one of these
files must be released under CC BY-SA 3.0 (or a compatible license). A game
that just plays the files is a collection, not an adaptation, so the game's
code and its other assets keep their own licenses.

## CC0 (no conditions)

CC0 is a public-domain dedication: copy, modify, redistribute and sell, with
no credit required. Credit is still welcome, and the authors are listed here.

| Folder / files | Author | Source |
|---|---|---|
| `backgrounds/` | André Mota (generated with Midjourney) | this repository; see `backgrounds/license.txt` |
| `k-rolling-ball/` | Kenney | https://www.kenney.nl ("Rolling Ball Assets") |
| `k-textures/` | Kenney | https://www.kenney.nl ("Retro Textures Fantasy") |
| `planets/` | Kenney | https://www.kenney.nl ("Planets") |
| `shooter/` | Kenney | https://www.kenney.nl ("Space Shooter Extension") |
| `space/` | Kenney | https://www.kenney.nl ("Space Shooter Redux") |
| `ninja/` | GameArt2D | https://www.gameart2d.com/ninja-adventure---free-sprites.html |
| `robot/` | GameArt2D | https://www.gameart2d.com/the-robot---free-sprites.html |
| `plane/` | GameArt2D | https://www.gameart2d.com/free-plane-sprite.html |
| `tilesets/` | GameArt2D | https://www.gameart2d.com/free-platformer-game-tileset.html |
| `pixel_adv/` | Pixel Frog | https://pixelfrog-assets.itch.io/pixel-adventure-2 |
| `misc/` (explosions, bullets) | OpenGameArt authors | links in `misc/license.txt` |
| `audio/Victory.mp3` | OpenGameArt | https://opengameart.org/content/victory |
| `audio/SuperHero_original_no_Intro.ogg` | OpenGameArt | https://opengameart.org/content/adventure-theme |
| `audio/footstep_*`, `audio/impact*` | Kenney | https://www.kenney.nl ("Impact Sounds") |
| `audio/explosion02.wav` | IdkMrGarcia | https://freesound.org/s/446625/ |
| `audio/explosion04.wav` | Anomaex | https://freesound.org/s/490266/ |
| `audio/projectile-hit.flac` | unfa | https://freesound.org/s/193429/ |
| `audio/sfx-hit-2.wav` | OwlStorm | https://freesound.org/s/404792/ |
| `audio/laser-big.wav` | mrspivey | https://freesound.org/s/805194/ |
| `audio/explode.flac` | SamsterBirdies, qubodup (mix) | links in `audio/License.txt` |

## Adding media

Every folder here needs a license file (`license.txt` or `License.txt`) that
names the source and license of each file. A test checks this
(`tests/test_media_licenses.py`). Only add files you can redistribute: CC0,
CC-BY or CC-BY-SA are fine. **NC** (non-commercial) and **ND** (no
derivatives) licenses, or files with no license, are not. Anything that needs
attribution goes in the section above, with its credit block ready to copy.
