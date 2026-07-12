#!/bin/bash
# ============================================
# Complete Mac Mini M4 Pipeline - FULL FIX
# Fixes: hand rendering, audio merge, subtitles
# ============================================
WORKDIR=~/whiteboard-workspace
cd "$WORKDIR"
PYTHON="$WORKDIR/.venv/bin/python3"
FFMPEG=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
FFPROBE=/opt/homebrew/opt/ffmpeg-full/bin/ffprobe
FONT=/System/Library/Fonts/Supplemental/Arial.ttf

echo "=== Step 0: Verify assets ==="
for f in assets/drawing-hand.png narration.mp3 endcard_permanent.png mac_gen.py scene_0*.png; do
  [ -f "$f" ] && echo "  ✅ $f" || echo "  ❌ $f MISSING"
done

# Step 1: Render 6 scenes
echo "=== Step 1: Render 6 scenes ==="
mkdir -p output_final
for sd in "scene_01.png:14000" "scene_02.png:18000" "scene_03.png:18000" "scene_04.png:15000" "scene_05.png:13000" "scene_06.png:6000"; do
  s="${sd%%:*}"; d="${sd##*:}"
  echo "Rendering $s (${d}ms)..."
  $PYTHON mac_gen.py "$s" --output-dir output_final --duration "$d" --no-color 2>&1 | tail -3
done

# Step 2: End card - match scene resolution
echo "=== Step 2: End card ==="
# First get clip resolution
CLIP_W=$($FFPROBE -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 output_final/clip_01.mp4 2>/dev/null)
CLIP_H=$($FFPROBE -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 output_final/clip_01.mp4 2>/dev/null)
echo "Scene resolution: ${CLIP_W}x${CLIP_H}"
$FFMPEG -y -i endcard_permanent.png -vf "scale=${CLIP_W}:${CLIP_H}:flags=lanczos" output_final/endcard_static.png 2>/dev/null
$FFMPEG -y -loop 1 -i output_final/endcard_static.png -c:v h264_videotoolbox -t 5 -pix_fmt yuv420p -r 60 -b:v 2000k output_final/endcard_clip.mp4 2>/dev/null
echo "End card: $($FFPROBE -v error -show_entries format=duration -of csv=p=0 output_final/endcard_clip.mp4 2>/dev/null)s"

# Step 3: Concat video
cd output_final
clips=($(ls vid_*_h264.mp4 | sort))
echo "Found ${#clips[@]} scene clips"
rm -f clip_*.mp4 concat_v.txt
for i in "${!clips[@]}"; do
  n=$((i+1)); cp "${clips[$i]}" "clip_$(printf "%02d" $n).mp4"
  echo "file clip_$(printf "%02d" $n).mp4" >> concat_v.txt
done
echo "file endcard_clip.mp4" >> concat_v.txt

# Verify hand was rendered - check clip files have content
ls -lh clip_*.mp4 endcard_clip.mp4

# Step 4: Merge video + subtitles + audio
$FFMPEG -f concat -safe 0 -i concat_v.txt -c copy merged_nosound.mp4 -y 2>/dev/null
VIDEO_DUR=$($FFPROBE -v error -show_entries format=duration -of csv=p=0 merged_nosound.mp4 2>/dev/null)
echo "Video duration: ${VIDEO_DUR}s"

NARRATION="$WORKDIR/narration.mp3"
echo "Audio duration: $($FFPROBE -v error -show_entries format=duration -of csv=p=0 "$NARRATION" 2>/dev/null)s"

# Step 5: One ffmpeg command - subtitles + audio merge
$FFMPEG -i merged_nosound.mp4 -i "$NARRATION" \
  -filter_complex \
  "[0:v]drawtext=fontfile=$FONT:text='Your dog_s body has a hidden cleaning system called the lymphatic system.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,0.24,4.52)',drawtext=fontfile=$FONT:text='Think of it as an internal drainage network.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,5.04,7.46)',drawtext=fontfile=$FONT:text='It removes waste, flushes out toxins, and fights off infections.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,8.13,12.45)',drawtext=fontfile=$FONT:text='Here_s what you need to know_ Lymph doesn_t have its own pump, unlike blood, which your dog_s heart keeps moving.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,12.99,19.99)',drawtext=fontfile=$FONT:text='Lymph only flows when muscles contract,':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,20.43,23.02)',drawtext=fontfile=$FONT:text='so when your furry friend is less active, that waste starts pooling.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,23.5,28.22)',drawtext=fontfile=$FONT:text='Dogs have four major Lymph node areas_ The neck nodes drain the face and ears,':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,28.72,33.92)',drawtext=fontfile=$FONT:text='the armpit nodes support immunity, the groin nodes handle the lower body, and the nodes behind the knees take care of the back legs.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,34.4,43.03)',drawtext=fontfile=$FONT:text='Massage technique is simple_ use your fingertips with very light pressure,':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,43.61,48.07)',drawtext=fontfile=$FONT:text='gentle circular strokes, moving from the face down toward the chest, six to ten repetitions per area.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,48.51,56.06)',drawtext=fontfile=$FONT:text='Do this daily.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,56.56,58.36)',drawtext=fontfile=$FONT:text='Benefits include stronger immunity.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,57.86,60.0)',drawtext=fontfile=$FONT:text='Less fatigue, better skin,':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,60.5,62.32)',drawtext=fontfile=$FONT:text='and improved circulation - your dog will feel more energetic and relaxed.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,62.72,67.71)',drawtext=fontfile=$FONT:text='But here_s a warning_ never massage over tumors, active infections, or if your dog has a fever.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,68.13,74.64)',drawtext=fontfile=$FONT:text='Always check with your vet first.':fontsize=16:fontcolor=white:bordercolor=black:borderw=3:x=(w-text_w)/2:y=h-text_h-20:enable='between(t,75.79,77.64)'[vout]" \
  -map "[vout]" -map 1:a:0 -c:v h264_videotoolbox -quality 95 -b:v 2500k -c:a aac -b:a 128k -pix_fmt yuv420p \
  "$WORKDIR/lymphatic_massage_mac_v2.mp4" -y 2>&1 | tail -5

echo "=== Step 6: Verify output ==="
$FFPROBE -v error -show_entries stream=codec_type -of default=noprint_wrappers=1 "$WORKDIR/lymphatic_massage_mac_v2.mp4" 2>/dev/null
DUR=$($FFPROBE -v error -show_entries format=duration -of csv=p=0 "$WORKDIR/lymphatic_massage_mac_v2.mp4" 2>/dev/null)
echo "Final video: ${DUR}s"
ls -lh "$WORKDIR/lymphatic_massage_mac_v2.mp4"
echo "=== DONE ==="
