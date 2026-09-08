"""Generate English narration from the fictional script and an original synth bed."""
import asyncio, re, subprocess, wave
import numpy as np
import edge_tts
from render_video import ROOT, NARRATION, ffmpeg

async def main():
    cache=ROOT/'audio'; cache.mkdir(exist_ok=True)
    for i,line in enumerate(NARRATION):
        target=cache/f'voice_{i}.mp3'
        if not target.exists():
            print(f'Narration {i+1}/6',flush=True)
            await edge_tts.Communicate(line,'en-US-AriaNeural',rate='+0%').save(str(target))
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
    filters=['[1:a]volume=0.55[bed]']; labels=['[bed]']; srt=[]
    for i,line in enumerate(NARRATION):
        path=cache/f'voice_{i}.mp3'; cmd+=['-i',str(path)]
        info=subprocess.run([ffmpeg(),'-i',str(path)],capture_output=True,text=True).stderr
        m=re.search(r'Duration: (\d+):(\d+):([\d.]+)',info)
        duration=int(m[1])*3600+int(m[2])*60+float(m[3])
        speed=max(1,duration/8.8)
        if speed>1.3: raise RuntimeError('Narration too long for comfortable delivery')
        delay=i*10000+500
        filters.append(f'[{i+2}:a]atempo={speed:.5f},adelay={delay},apad,atrim=duration=60[vo{i}]')
        labels.append(f'[vo{i}]')
        print(f'Voice {i+1}: {duration:.2f}s, playback speed {speed:.2f}',flush=True)
        srt.append(f'{i+1}\n00:00:{i*10:02d},500 --> 00:00:{i*10+9:02d},500\n{line}\n')
    filters.append(''.join(labels)+'amix=inputs=7:dropout_transition=0,volume=7,alimiter=limit=0.89,apad,atrim=duration=60[out]')
    cmd+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[out]','-c:v','copy','-c:a','aac','-b:a','192k','-t','60','-movflags','+faststart',str(ROOT/'b2b_showcase_60s.mp4')]
    with (ROOT/'audio_mix.log').open('w') as log: subprocess.run(cmd,stderr=log,check=True)
    (ROOT/'b2b_showcase_en.srt').write_text('\n'.join(srt),encoding='utf-8')
    (ROOT/'voiceover.txt').write_text('\n\n'.join(f'{i*10:02d}s: {s}' for i,s in enumerate(NARRATION)),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
