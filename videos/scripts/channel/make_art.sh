#!/bin/sh
# The channel's art and the videos' thumbnails, drawn by channel_art.py.
#
#   sh videos/scripts/channel/make_art.sh        (from the repository root)
#
# Writes videos/finals/channel/: avatar.png (800x800), banner.png (2560x1440);
# each thumbnail (1280x720, under YouTube's 2 MB) beside its video in
# videos/finals/, with the video's name: scena_<video>.jpg, buildup_<id>.jpg;
# a Short's cover is upright (1080x1920: the title on top, the still below).
# The stills come from the videos (ffmpeg); a build-up's still is its game,
# without the code panel and the caption (1530 x 1100 from (1030, 165) of
# 2560x1440). A thumbnail shows the right 720 px of a still scaled to 720 high:
# a crop puts the action there. The code video's thumbnail with a play mark is
# the README's poster: docs/assets/readme/video-code.jpg.
set -e
SCRIPTS=videos/scripts/channel
FINALS=videos/finals
REC=videos/recordings
STILLS=$REC/art/stills
TMP=$(mktemp -d)
mkdir -p "$FINALS/channel" "$STILLS"

draw() {    # draw NAME SIZE  (env: CHANNEL_ART and the THUMB_* of channel_art.py)
    rm -rf "$TMP/$1"
    python tools/video/record_game.py $SCRIPTS/channel_art.py --seconds 0.3 --size "$2" \
        --supersample 2 --frames-dir "$TMP/$1" >/dev/null
    ls "$TMP/$1"/frame_*.png | tail -1
}

still() {   # still VIDEO SECONDS NAME [game | W:H:X:Y | flip:W:H:X:Y]
    vf="null"
    [ "$4" = game ] && vf="crop=1530:1100:1030:165"
    [ -n "$4" ] && [ "$4" != game ] && vf="crop=$4"
    case "$4" in flip:*) vf="hflip,crop=${4#flip:}" ;; esac    # the crop is in the mirrored frame
    ffmpeg -v error -y -ss "$2" -i "$1" -frames:v 1 -vf "$vf" -q:v 2 "$STILLS/$3.jpg"
}

erase() {   # erase NAME W:H:X:Y DY: cover a box of the still (its caption) with the strip DY px below
    w=${2%%:*}; r=${2#*:}; h=${r%%:*}; r=${r#*:}; x=${r%%:*}; y=${r#*:}
    ffmpeg -v error -y -i "$STILLS/$1.jpg" -filter_complex \
        "[0]split[a][b];[b]crop=$w:$h:$x:$((y + $3))[p];[a][p]overlay=$x:$y" -q:v 2 "$TMP/erased.jpg"
    mv "$TMP/erased.jpg" "$STILLS/$1.jpg"
}

thumb() {   # thumb OUT NAME KICKER[|TAGLINE] "LINE|LINE" FOOTER [SUBTITLE [NOTE]]  (OUT: under videos/finals/)
    export THUMB_IMAGE="$PWD/$STILLS/$2.jpg" THUMB_KICKER="$3" THUMB_TITLE="$4" \
        THUMB_FOOTER="$5" THUMB_SUB="$6" THUMB_NOTE="$7" CHANNEL_ART=${ART:-thumb}
    png=$(draw "$2" "${SIZE:-1280x720}")
    ffmpeg -v error -y -i "$png" -q:v 2 "$FINALS/$1.jpg"
    echo "$FINALS/$1.jpg"
}

tall_thumb() {  # tall_thumb OUT NAME KICKER "LINE|LINE" SUBTITLE: a Short's cover
    ART=thumb_tall SIZE=1080x1920
    thumb "$1" "$2" "$3" "$4" "" "$5"
    ART= SIZE=
}

take() {    # take OUT RECORD_GAME_ARGS...: a take only the thumbnails use, recorded once
    out=$1; shift
    [ -f "$REC/$out" ] || python tools/video/record_game.py "$@" --out "$PWD/$REC/$out"
}

cp "$(CHANNEL_ART=avatar draw avatar 800x800)" "$FINALS/channel/avatar.png"
cp "$(CHANNEL_ART=banner draw banner 2560x1440)" "$FINALS/channel/banner.png"

# the teasers show the showcases, not their own frames: Pulse's mandala and
# Guardian with two explosions by the ring, mirrored: the explosions were left
# of the ring, under the title panel; the HUD is cropped out, so nothing reads
# backwards
take pulse/music_video.mp4 examples/pulse.py --seconds 62 --size 2560x1600
take guardian/thumbs/seed3.mp4 examples/guardian.py --pilot guard_ring --seed 3 \
    --lead 74 --seconds 56 --size 2560x1440
still $REC/pulse/music_video.mp4 12.55 teaser 1300:1300:630:150   # the triangles a little off the star
still $REC/guardian/thumbs/seed3.mp4 38.25 teaser2 flip:1200:1200:848:240
still $FINALS/promo/scena_code.mp4 63 code 2300:1294:260:146    # below the corner mark
erase code 580:76:1466:896 80                   # "A star every half second." (step by step, below)
# the later promos: each one's own picture, clear of its captions and headers
P=$FINALS/promo
still $P/scena_teaser3.mp4 16 teaser3 1180:1180:920:260        # the tutorial's staircase
still $P/scena_teaser3_vertical.mp4 3 teaser3_vertical 960:950:60:445    # its opening game
still $P/scena_engine.mp4 104 engine 1300:1300:700:140         # lit lines beside the pegs
still $P/scena_effects.mp4 104.5 effects 1200:1200:670:235     # the portal, "They compose"
still $P/scena_flow.mp4 26 flow 1400:1400:600:0                # the ring, foes spiralling out
still $P/scena_salvo.mp4 22.45 salvo 1030:1030:1320:180        # the boss in the tunnel
B=$FINALS/buildups
end() { python -c "import sys; print(float(sys.argv[1]) - 1.5)" \
    "$(ffprobe -v error -show_entries format=duration -of csv=p=0 $B/buildup_$1.mp4)"; }
for b in first_script catch_stars balls ninja_1_run oscilloscope spinning_bars; do
    still $B/buildup_$b.mp4 "$(end $b)" $b game
done
still $B/buildup_ships_1.mp4 105 ships_1 game
still $B/buildup_movement.mp4 44 movement 900:900:1346:240   # the ring and the ship flying to it
still $B/buildup_demo100.mp4 20 demo100 game
still $B/buildup_old_school.mp4 40 old_school game

# a cover whose title does not say what Scena is says it under the name
WHAT="SCENA|Python game engine"
thumb promo/scena_teaser teaser   "SCENA"            "2D games|in Python"      "pip install scena"
thumb promo/scena_teaser2 teaser2  "SCENA"            "Python|game engine|for beginners" "" "simple, expressive code"
thumb promo/scena_code code     "$WHAT"            "Real code,|real games"   "short programs, and what they do" \
    "" "975,200,24:step by step"
# the README's poster for the code video: its thumbnail with a play mark on the game
export THUMB_PLAY=975,446
thumb promo/scena_code_poster code "$WHAT" "Real code,|real games" "short programs, and what they do" \
    "" "975,200,24:step by step"
unset THUMB_PLAY
mv "$FINALS/promo/scena_code_poster.jpg" docs/assets/readme/video-code.jpg
thumb promo/scena_teaser3 teaser3 "$WHAT"           "Built for|learning"      "" "simple, yet powerful"
tall_thumb promo/scena_teaser3_vertical teaser3_vertical "SCENA" "Python|game engine" "built for learning"
thumb promo/scena_engine engine   "$WHAT"            "Watch the|engine work"   "" "real code, run as it is typed"
thumb promo/scena_effects effects "$WHAT"            "100+ visual|effects"     "" "built in, one line each"
thumb promo/scena_flow flow       "$WHAT"            "Short and|to the point"  "" "no boilerplate, no ceremony"
thumb promo/scena_salvo salvo     "$WHAT"            "Make something|beautiful" "" "easy to begin, room to grow"
thumb buildups/buildup_first_script first_script  "SCENA TUTORIAL"  "Your first|script"   "34 lines, step by step"
thumb buildups/buildup_catch_stars catch_stars   "SCENA TUTORIAL"  "Catch the|stars"     "a game in 33 lines"
thumb buildups/buildup_ships_1 ships_1       "SCENA TUTORIAL"  "Ships"               "a shooter in 66 lines"
thumb buildups/buildup_balls balls         "SCENA TUTORIAL"  "Balls"               "39 lines, step by step"
thumb buildups/buildup_movement movement      "SCENA TUTORIAL"  "Movement"            "30 lines, step by step"
thumb buildups/buildup_ninja_1_run ninja_1_run   "SCENA TUTORIAL"  "Ninja"               "a platformer in 46 lines"
thumb buildups/buildup_oscilloscope oscilloscope  "SCENA TUTORIAL"  "Oscilloscope"        "39 lines, step by step"
thumb buildups/buildup_spinning_bars spinning_bars "SCENA TUTORIAL"  "Spinning|bars"       "34 lines, step by step"
thumb buildups/buildup_demo100 demo100       "SCENA DEMO"      "Dancing|triangles"   "a demo in about 120 lines"
thumb buildups/buildup_old_school old_school    "SCENA DEMO"      "Old-school|megademo" "eight classic effects, in Python"
rm -rf "$TMP"
