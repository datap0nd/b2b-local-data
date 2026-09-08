# B2B — one-minute showcase

[Watch or download the video](b2b_showcase_60s.mp4)

English narration, burned-in captions, an original synthesized soundtrack,
and animated illustrative interfaces. H.264/AAC, 1920 × 1080, 30 fps, 60 seconds.

The editorial reference is the local Scribble `promo_video/scribble_showcase_60s.mp4`:
dark grid, blue/violet accents, interface-led scenes, captions and narration.
No Scribble footage, narration or business data is reused.

All names, amounts and records in this video are invented. A persistent badge
labels the demo. The interfaces are purpose-built illustrations of the B2B
workflow, not a screen recording or evidence of a live connection. The renderer
does not read application datasets, configuration, credentials or saved history.

The example contains six opportunities: Proposal EUR 60,000, Qualification
EUR 40,000 and Negotiation EUR 20,000, two opportunities per stage. The supporting
records scene shows three example rows from that set. Quality review is a separate
capability illustration, not a claim that this example has passed validation.
Capabilities and colors are grounded in the repository README and frontend.

## Timeline

- 00–10: A conversational route from data to answers; fictional-data disclosure.
- 10–20: Ask, validate and calculate.
- 20–30: Animated chart, then the same values in a table.
- 30–40: Supporting opportunities, product details and CSV.
- 40–50: Quality review, freshness and saved-answer provenance.
- 50–60: Closing product message.

## Rebuild

On Windows, install `requirements.txt` and set `FFMPEG_EXE` to an FFmpeg executable
with libx264 and AAC support. The renderer uses the Windows Segoe UI font.

```powershell
python render_video.py --preview
python render_video.py
python build_audio.py
```

Only the invented narration is sent to the Edge TTS service. Visuals and music
are generated locally. The audio cache and silent intermediate are ignored.
The final MP4, poster, contact sheet, captions and editable source are included.
