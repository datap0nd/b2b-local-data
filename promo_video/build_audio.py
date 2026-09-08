"""Generate English narration from the fictional script and an original synth bed."""
import asyncio, re, subprocess, wave, hashlib, sys, json
import numpy as np
import edge_tts
from render_video import ROOT, NARRATION, CUES, ffmpeg

async def main():
    cache=ROOT/'audio'; cache.mkdir(exist_ok=True)
    voices=[]; boundaries=[]
    for i,line in enumerate(NARRATION):
        target=cache/f'voice_{i}_{hashlib.sha256(line.encode()).hexdigest()[:10]}.mp3'
        voices.append(target)
        timing=target.with_suffix('.json');boundaries.append(timing)
        if not target.exists() or not timing.exists():
            print(f'Narration {i+1}/{len(NARRATION)}',flush=True)
            words=[]
            with target.open('wb') as audio:
                async for chunk in edge_tts.Communicate(line,'en-US-AriaNeural',rate='+0%',boundary='WordBoundary').stream():
                    if chunk['type']=='audio': audio.write(chunk['data'])
                    elif chunk['type']=='WordBoundary': words.append({k:chunk[k] for k in ['offset','duration','text']})
            timing.write_text(json.dumps(words),encoding='utf-8')
    if '--voices-only' in sys.argv: return
    sr=48000; times=np.arange(sr*60)/sr; bed=np.zeros(len(times))
    for i,notes in enumerate([(130.81,164.81,196),(110,130.81,164.81),(87.31,110,130.81),(98,123.47,146.83),(130.81,164.81,196),(98,130.81,196)]):
        mask=(times>=i*10)&(times<(i+1)*10); local=times[mask]-i*10
        env=np.minimum(local/1.5,1)*np.minimum((10-local)/1.5,1)
        for freq in notes: bed[mask]+=.018*np.sin(2*np.pi*freq*local)*env
        for beat in range(5):
            tt=local-beat*2; hit=tt>=0
            bed[np.where(mask)[0][hit]]+=.025*np.sin(2*np.pi*notes[beat%3]*4*tt[hit])*np.exp(-tt[hit]*4)
    with wave.open(str(cache/'music.wav'),'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((bed*32767).astype('<i2').tobytes())
    cmd=[ffmpeg(),'-y','-i',str(ROOT/'silent.mp4'),'-i',str(cache/'music.wav')]
    filters=['[1:a]volume=0.55[bed]']; labels=['[bed]']; events=[]
    for i,line in enumerate(NARRATION):
        path=voices[i]; cmd+=['-i',str(path)]
        info=subprocess.run([ffmpeg(),'-i',str(path)],capture_output=True,text=True).stderr
        m=re.search(r'Duration: (\d+):(\d+):([\d.]+)',info)
        duration=int(m[1])*3600+int(m[2])*60+float(m[3])
        slot=(CUES[i+1] if i+1<len(CUES) else 60)-CUES[i]-.7
        speed=max(1,duration/slot)
        if speed>1.3: raise RuntimeError('Narration too long for comfortable delivery')
        delay=CUES[i]*1000+250
        filters.append(f'[{i+2}:a]atempo={speed:.5f},adelay={delay},apad,atrim=duration=60[vo{i}]')
        labels.append(f'[vo{i}]')
        print(f'Voice {i+1}: {duration:.2f}s, playback speed {speed:.2f}',flush=True)
        words=json.loads(boundaries[i].read_text(encoding='utf-8'));group=[]
        original=line.split()
        if len(original)!=len(words):raise RuntimeError('Narration word alignment changed')
        for word,spelling in zip(words,original):
            if re.sub(r'\W','',word['text']).lower()!=re.sub(r'\W','',spelling).lower():raise RuntimeError('Narration word mismatch')
            word['text']=spelling
        def flush():
            if not group:return
            start=CUES[i]+.25+group[0]['offset']/10000000/speed
            end=CUES[i]+.25+(group[-1]['offset']+group[-1]['duration'])/10000000/speed
            events.append((start,min(59.95,end+.12),' '.join(w['text'] for w in group)))
        for word in words:
            if group and len(' '.join(w['text'] for w in group)+' '+word['text'])>72:flush();group=[]
            group.append(word)
            if word['text'].endswith(('.', '?', '!')):flush();group=[]
        flush()
    count=len(labels)
    filters.append(''.join(labels)+f'amix=inputs={count}:dropout_transition=0,volume={count},alimiter=limit=0.89,apad,atrim=duration=60[out]')
    def timestamp(t,ass=False):
        ms=round(t*1000);h,rem=divmod(ms,3600000);m,rem=divmod(rem,60000);s,ms=divmod(rem,1000)
        return f'{h}:{m:02d}:{s:02d}.{ms//10:02d}' if ass else f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
    events=[(start,min(end,events[i+1][0]-.02) if i+1<len(events) else end,line) for i,(start,end,line) in enumerate(events)]
    srt=[f'{i+1}\n{timestamp(start)} --> {timestamp(end)}\n{line}\n' for i,(start,end,line) in enumerate(events)]
    (ROOT/'b2b_showcase_en.srt').write_text('\n'.join(srt),encoding='utf-8')
    ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bottom,Segoe UI,32,&H003B2318,&H003B2318,&H00F0F4F5,&H00F0F4F5,0,0,0,0,100,100,0,0,1,1,0,2,100,100,29,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    ass+='\n'.join(f'Dialogue: 0,{timestamp(start,True)},{timestamp(end,True)},Bottom,,0,0,0,,{line}' for start,end,line in events)
    (ROOT/'edit').mkdir(exist_ok=True);(ROOT/'edit/subtitles.ass').write_text(ass,encoding='utf-8')
    cmd+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[out]','-vf','ass=edit/subtitles.ass','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-t','60','-movflags','+faststart',str(ROOT/'b2b_showcase_60s.mp4')]
    with (ROOT/'audio_mix.log').open('w') as log: subprocess.run(cmd,stderr=log,check=True,cwd=ROOT)
    (ROOT/'voiceover.txt').write_text('\n\n'.join(f'{CUES[i]:02d}s: {s}' for i,s in enumerate(NARRATION)),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
