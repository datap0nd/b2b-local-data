"""Minimal 60-second edit of actual frontend recordings with synthetic API replies."""
from pathlib import Path
from functools import lru_cache
import os, subprocess, argparse
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
W,H,FPS,DURATION=1920,1080,30,60
CUES=[0,4,20,36,52]
NARRATION=[
 'Your pipeline. Answers in seconds.',
 'Need the open pipeline value? Just ask. The answer appears, with the opportunities behind it. One question. A clear number.',
 'Want the breakdown? Ask for value by stage. See where the pipeline sits, then switch from the chart to the data in a click.',
 'Need the deals in negotiation? Ask directly. Find the matching opportunities, see their values, and download the result. Keep your attention on the decision.',
 'B2B. Answers in seconds. Move forward.'
]
INK='#18233b'; BLUE='#315bd6'; PAPER='#f5f4f0'
def ffmpeg(): return os.environ.get('FFMPEG_EXE','ffmpeg')
@lru_cache(None)
def font(size,bold=False):
 return ImageFont.truetype(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/('segoeuib.ttf' if bold else 'segoeui.ttf')),size)
def text(d,xy,s,size=30,color=INK,bold=False): d.text(xy,s,font=font(size,bold),fill=color)
def center(d,y,s,size=30,color=INK,bold=False): text(d,((W-d.textlength(s,font=font(size,bold)))/2,y),s,size,color,bold)
def art():
 cache=ROOT/'edit';cache.mkdir(exist_ok=True)
 for name in ['intro','outro']:
  im=Image.new('RGB',(W,H),PAPER);d=ImageDraw.Draw(im)
  center(d,205,'B2B',40,BLUE,True)
  center(d,365,'Your pipeline.' if name=='intro' else 'Ask. Get answers.',96,INK,True)
  center(d,487,'Answers in seconds.' if name=='intro' else 'Move forward.',96,BLUE,True)
  if name=='outro':center(d,696,'Less searching. More deciding.',35,'#65728a')
  center(d,1020,'Fictional data · Scripted demo timing',23,'#65728a')
  im.save(cache/f'{name}.png')
 for i,headline in enumerate(['Ask. Get the number.','Ask. See the breakdown.','Ask. Find the deals.']):
  im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im)
  text(d,(100,29),'B2B',35,BLUE,True);text(d,(295,22),headline,48,INK,True)
  text(d,(100,1037),'Fictional data · Scripted ~2-second responses',22,'#65728a')
  text(d,(1620,1037),f'0{i+1} / 03',22,'#65728a')
  im.save(cache/f'overlay-{i}.png')
 return cache
def run(args):
 with (ROOT/'render.log').open('a') as log:subprocess.run([ffmpeg(),'-y',*args],stderr=log,check=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--preview',action='store_true');ap.add_argument('--concat-only',action='store_true');args=ap.parse_args();cache=art()
 if args.concat_only:
  run(['-f','concat','-safe','0','-i',(cache/'concat.txt').as_posix(),'-c','copy','-movflags','+faststart',str(ROOT/'silent.mp4')]);return
 if args.preview:
  sheet=Image.new('RGB',(1440,540),PAPER)
  images=[cache/'intro.png',*[ROOT/'captures'/f'result-{i}.png' for i in range(3)],cache/'outro.png']
  for i,p in enumerate(images):sheet.paste(Image.open(p).convert('RGB').resize((480,270)),((i%3)*480,(i//3)*270))
  sheet.save(ROOT/'contact_sheet.jpg');Image.open(cache/'outro.png').convert('RGB').save(ROOT/'poster.jpg');return
 encode=['-r','30','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-an']
 for name,duration in [('intro',4),('outro',8)]:
  run(['-loop','1','-i',str(cache/f'{name}.png'),'-t',str(duration),*encode,str(cache/f'{name}.mp4')])
 for i in range(3):
  run(['-i',str(ROOT/'captures'/f'ui-{i}.webm'),'-loop','1','-i',str(cache/f'overlay-{i}.png'),'-filter_complex','[0:v]scale=1600:900,pad=1920:1080:160:116:color=0xf5f4f0[ui];[ui][1:v]overlay=0:0:shortest=1[v]','-map','[v]','-t','16',*encode,str(cache/f'ui-{i}.mp4')])
  print(f'Edited UI scene {i+1}/3',flush=True)
 names=['intro','ui-0','ui-1','ui-2','outro']
 (cache/'concat.txt').write_text('\n'.join(f"file '{n}.mp4'" for n in names))
 run(['-f','concat','-safe','0','-i',(cache/'concat.txt').as_posix(),'-c','copy','-movflags','+faststart',str(ROOT/'silent.mp4')])
if __name__=='__main__':main()
