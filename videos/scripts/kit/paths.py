"""Where the video scripts read and write (videos/README.md).

  videos/finals/<series>/       what is uploaded: promo/, buildups/, channel/
  videos/recordings/<video>/    what a video is made from and can be made again:
                                its cue sheet, its music cut, its takes' stills
  videos/recordings/<game>/     the takes (tools/video/record_game.py)
  videos/recordings/masters.nosync/<video>.mov
                                the ProRes masters (iCloud does not sync a
                                ``.nosync`` folder); delete one once its video
                                is accepted
"""

import os

KIT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(KIT)
VIDEOS = os.path.dirname(SCRIPTS)
REPO = os.path.dirname(VIDEOS)
EXAMPLES = os.path.join(REPO, "examples")
MUSIC = os.path.join(EXAMPLES, "media", "music")
RECORDINGS = os.path.join(VIDEOS, "recordings")
MASTERS = os.path.join(RECORDINGS, "masters.nosync")
FINALS = os.path.join(VIDEOS, "finals")


def work(video):
    """``videos/recordings/<video>/``, made if missing: a video's own material."""
    path = os.path.join(RECORDINGS, video)
    os.makedirs(path, exist_ok=True)
    return path


def recording(path):
    """A take as a cue names it, ``<game>/<take>.mp4``. Cue sheets written
    before videos/ (``recordings/<game>/<take>.mp4``, the code video's
    fragments in ``code_video/``) still resolve."""
    for old, new in (("recordings/", ""), ("code_video/", "code/")):
        if path.startswith(old):
            path = new + path[len(old):]
    return os.path.join(RECORDINGS, path)
