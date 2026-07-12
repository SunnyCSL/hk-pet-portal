# Pet Health Videos
Whiteboard animation video production pipeline for pet health education content.

## Folder Structure
```
pet-health-videos/
├── scenes/          # Scene PNG images (570x1024, 9:16, NO text)
├── scripts/         # Generator + render scripts  
├── narration/       # TTS narration audio files
├── templates/       # End card, intros, reusable elements
├── output/          # Rendered final MP4 videos
├── assets/          # Shared assets (hand image, drawing fonts)
└── docs/            # Project documentation
```

## Naming Conventions
- **Scenes:** `scene_{NN}_{topic}.png` (e.g. `scene_01_title.png`, `scene_02_lymph-nodes.png`)
- **Videos:** `{topic}_{language}_v{NN}.mp4` (e.g. `lymphatic-massage_en_v01.mp4`)
- **Audio:** `narration_{topic}_{lang}.mp3`
- **Scripts:** `{action}_{platform}.sh` (e.g. `render_mac.sh`, `gen_scenes_mac.py`)

## Pipeline
1. Generate scenes via FLUX AI (image_generate tool)
2. Render whiteboard animation (OpenCV - mac_gen.py)
3. Add subtitles + audio (ffmpeg drawtext)
4. Encode with VideoToolbox (h264_videotoolbox)

