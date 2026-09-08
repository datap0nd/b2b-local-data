# B2B — answers in seconds

[Watch the one-minute video](b2b_showcase_60s.mp4)

A minimal, interface-led product demo: 48 of 60 seconds show recordings of the
actual shipped B2B frontend, including typing, pending states, results, switching
Chart/Data, and downloading CSV. English narration, quiet original synth music,
and separate English subtitles. H.264/AAC, 1920 × 1080, 30 fps.

## Demo scope

All business data is invented. The capture serves only `web/dist` and intercepts
every API request with a fictional response. No application backend, Salesforce
extract, database, credentials or user history is accessed. The frontend itself
is unmodified. This is a real UI recording with simulated responses, not a live
model or database performance benchmark. The footer labels the scripted timing.

The mock response delay is 1.45 seconds; browser interaction and rendering bring
the observed click-to-visible-result time to approximately two seconds. Actual
capture measurements are in `captures/manifest.json`. The video keeps that
interaction at normal speed. It does not assert a measured production SLA.

Six fictional opportunities sum to EUR 120,000: Negotiation 60,000, Qualified
40,000, Identified 20,000. Two opportunities are in each stage. The negotiation
query and exported CSV contain the same two records, EUR 35,000 and EUR 25,000.

## Edit

- 00–04: “Your pipeline. Answers in seconds.”
- 04–20: Type the question; the EUR 120,000 result appears with supporting records.
- 20–36: Ask for the stage breakdown; switch between the chart and table.
- 36–52: Ask for negotiation deals; inspect the two records and download CSV.
- 52–60: “Ask. Get answers. Move forward.”

The earlier Scribble-inspired graphic treatment has been replaced by a warm
white background, concise headlines and actual UI footage.

## Rebuild

Requires Windows Segoe UI, Python packages in `requirements.txt`, Node.js,
Playwright (`npm install --no-save playwright` here), Chrome, and FFmpeg with
libx264/AAC. Set `FFMPEG_EXE` and optionally `CHROME_EXE`. To reuse an installed
Playwright package, set `PLAYWRIGHT_PACKAGE` to its enclosing package.json.

```powershell
node capture_ui.cjs
python render_video.py --preview
python render_video.py
python build_audio.py
```

Only the fictional narration is sent to Edge TTS. The audio and edit caches are
ignored. The source UI clips, fixture capture script, response-time manifest,
fictional CSV, final MP4, captions, poster and contact sheets are included.
