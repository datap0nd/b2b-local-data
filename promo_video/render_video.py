"""Render the fictional B2B showcase. No application data or network reads."""
from pathlib import Path
from functools import lru_cache
import math, os, subprocess, argparse
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, FPS, DURATION = 1920, 1080, 30, 60
BG, WHITE, INK, BLUE, MUTED = '#0b0e18', '#f6f8ff', '#18233b', '#608cff', '#a3aec4'
SCENES = [
 ('FROM QUESTION TO CLARITY', 'Your pipeline.\nOne conversation.', 'Turn Salesforce extracts into answers you can inspect.'),
 ('01 / ASK', 'Start with a question.', 'Plain language in. A validated query plan behind every answer.'),
 ('02 / UNDERSTAND', 'See the shape of the answer.', 'Switch between charts and data without another model call.'),
 ('03 / INSPECT', 'Every total has a trail.', 'Open the supporting opportunities. Explore products. Export CSV.'),
 ('04 / REVIEW', 'Keep the caveats visible.', 'Review data quality and the verified data-update time.'),
 ('B2B / LOCAL DATA', 'Ask. Understand. Act.', 'Conversational analysis. Traceable answers. Local workflow.'),
]
NARRATION = [
 'Your sales data holds the answers. B2B makes them easier to find. This entire demonstration uses fictional data.',
 'Ask a question in plain language. A locally hosted model creates a validated plan, and a deterministic engine calculates the answer.',
 'See open opportunities by stage. Switch between charts and data, then refine the conversation to focus on what matters.',
 'Go beyond the headline. Inspect supporting opportunities, explore product details, and export the complete result to CSV.',
 'Keep quality issues visible. Review affected fields, check data freshness, and revisit saved answers with their original context.',
 'From Salesforce extracts to a clearer commercial picture. B2B. Ask, understand, and act, with answers you can trace.',
]

@lru_cache(None)
def font(n, bold=False):
    root = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    return ImageFont.truetype(str(root / ('segoeuib.ttf' if bold else 'segoeui.ttf')), n)

def txt(d,x,y,s,n=30,c=WHITE,b=False):
    d.multiline_text((x,y),s,font=font(n,b),fill=c,spacing=10)

def box(d,coords,fill='#171e2d',outline=None):
    d.rounded_rectangle(coords,18,fill=fill,outline=outline,width=2)

def smooth(x):
    x=max(0,min(1,x)); return 1-(1-x)**3

@lru_cache(None)
def base(idx):
    im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im)
    for x in range(0,W,80): d.line((x,0,x,H),fill='#141a29')
    for y in range(0,H,80): d.line((0,y,W,y),fill='#141a29')
    d.ellipse((1590,-310,2190,290),fill='#263f78')
    d.ellipse((-370,850,230,1450),fill='#332266')
    txt(d,100,48,'B2B',30,b=True)
    box(d,(1390,42,1818,96),'#1e2b43')
    txt(d,1410,53,'FICTIONAL DEMO DATA',24, '#b7ceff',True)
    tag,title,sub=SCENES[idx]
    txt(d,100,142,tag,23,BLUE,True)
    txt(d,100,182,title,66 if idx!=0 else 76,b=True)
    txt(d,100,365 if idx==0 else 274,sub,29,MUTED)
    return im

def shell(d):
    box(d,(100,355,1820,900),'#f5f4f0')
    d.rounded_rectangle((100,355,1820,416),18,fill='#ffffff')
    txt(d,135,370,'B2B',27,INK,True)
    txt(d,235,376,'Illustrative interface',21,'#65728a')
    txt(d,1500,375,'Saved conversations',21,'#65728a')

def frame(t):
    idx=min(5,int(t//10)); u=t-idx*10
    im=base(idx).copy(); d=ImageDraw.Draw(im)
    p=smooth(u/1.1)
    if idx==0:
        for j,(a,b) in enumerate([('Ask naturally','Which opportunities are open?'),('Calculate consistently','Validated plan + deterministic engine'),('Inspect the evidence','Charts, records and quality review')]):
            x=100+j*580; y=490+int((1-smooth((u-j*.35)/1.2))*65)
            box(d,(x,y,x+540,y+275),outline='#33415a')
            txt(d,x+32,y+30,f'0{j+1}',40,BLUE,True)
            txt(d,x+32,y+105,a,35,b=True)
            # Deliberate line breaks keep the opening cards comfortably readable.
            lines=[['Which opportunities','are open?'],['Validated plan +','deterministic engine'],['Charts, records and','quality review']][j]
            txt(d,x+32,y+165,'\n'.join(lines),25,MUTED)
    elif idx==1:
        shell(d)
        question='Show open opportunities by stage'
        box(d,(650,453,1745,537),'#e7edff')
        txt(d,685,471,question[:int(max(0,u-.5)*25)],36,INK)
        for j,(a,b) in enumerate([('Interpret','Local model'),('Validate','Allowed query plan'),('Calculate','Deterministic engine')]):
            x=180+j*530; y=600+int((1-smooth((u-1.4-j*.4)))*30)
            box(d,(x,y,x+470,y+170),'#ffffff','#e0e4eb')
            txt(d,x+25,y+28,a,34,INK,True); txt(d,x+25,y+87,b,27,'#65728a')
        txt(d,180,810,'One question. A structured, inspectable result.',28,'#315bd6',True)
    elif idx==2:
        shell(d); txt(d,145,443,'Open opportunities by stage',34,INK,True)
        txt(d,145,494,'6 opportunities  |  EUR 120,000',27,'#65728a')
        chart=u<6.7
        box(d,(1430,442,1765,494),'#e7edff'); txt(d,1450,451,'Chart   /   Data',25,'#315bd6',True)
        vals=[60000,40000,20000]; labels=['Proposal','Qualification','Negotiation']
        for j,(v,label) in enumerate(zip(vals,labels)):
            y=565+j*88; txt(d,160,y,label,28,INK)
            if chart:
                length=max(1,int(860*v/60000*smooth((u-.4-j*.2)/1.2)))
                box(d,(465,y,465+length,y+47),['#315bd6','#6685e8','#9caff2'][j])
                txt(d,1360,y,f'EUR {v:,.0f}',29,INK,True)
            else:
                d.line((460,y+53,1710,y+53),fill='#d4dbea',width=2)
                txt(d,560,y,'2 opportunities',29,INK); txt(d,1270,y,f'EUR {v:,.0f}',29,INK,True)
        txt(d,160,833,'Chart and table show the same fictional result.',24,'#65728a')
    elif idx==3:
        shell(d); txt(d,145,442,'Supporting opportunities',34,INK,True)
        cols=[150,760,1200,1530]
        for x,s in zip(cols,['Opportunity','Stage','Amount','Currency']): txt(d,x,512,s,23,'#65728a',True)
        rows=[['Demo opportunity A','Proposal','35,000','EUR'],['Demo opportunity B','Proposal','25,000','EUR'],['Demo opportunity C','Qualification','22,000','EUR']]
        for j,row in enumerate(rows):
            y=568+j*72; d.line((145,y+56,1755,y+56),fill='#e0e4eb',width=2)
            for x,s in zip(cols,row): txt(d,x,y,s,27,INK)
        box(d,(145,800,900,861),'#e7edff'); txt(d,169,813,'Product details  /  Summary and Products',25,'#315bd6')
        box(d,(1400,800,1750,861),'#315bd6'); txt(d,1432,813,'Download full CSV',25,'#ffffff',True)
    elif idx==4:
        shell(d)
        for j,(title,body,color) in enumerate([
            ('Quality review','Affected fields\nAmount comparisons\nFlagged records','#fff7df'),
            ('Data freshness','Verified update time\nUnknown stays unknown\nContext for each answer','#e7edff'),
            ('Saved answers','Original provenance\nRevisit the conversation\nRun with current data','#e5f4ec')]):
            x=150+j*550; y=475+int((1-smooth((u-j*.3)/1.1))*35)
            box(d,(x,y,x+510,y+330),color)
            txt(d,x+30,y+30,title,34,INK,True); txt(d,x+30,y+109,body,29,'#4b5871')
        txt(d,150,836,'Review the evidence before making a decision.',25,'#65728a')
    else:
        for j,(a,b) in enumerate([('ASK','Plain-language questions'),('UNDERSTAND','Charts + supporting records'),('ACT','Review + export')]):
            x=100+j*580; y=430+int((1-smooth((u-j*.25)/1.1))*40)
            box(d,(x,y,x+540,y+230),outline='#33415a')
            txt(d,x+32,y+37,a,36,BLUE,True); txt(d,x+32,y+112,b,29,b=True)
        txt(d,100,734,'B2B Salesforce Query Agent',48,b=True)
        txt(d,100,807,'Illustrative demo. All names, records and amounts are invented.',27,MUTED)
    # Burned-in captions use two balanced lines at a readable size.
    words=NARRATION[idx].split(); lines=[]; line=''
    for word in words:
        test=(line+' '+word).strip()
        if d.textlength(test,font=font(27))>1600: lines.append(line); line=word
        else: line=test
    lines.append(line)
    box(d,(95,944,1825,1040),'#080b12')
    for j,line in enumerate(lines):
        x=(W-d.textlength(line,font=font(27)))/2; txt(d,x,953+j*37,line,27)
    d.rectangle((0,1074,int(W*t/60),1079),fill=BLUE)
    # Short scene fade-in, followed by long reading holds.
    if u<.22: im=Image.blend(Image.new('RGB',(W,H),BG),im,smooth(u/.22))
    return im

def ffmpeg():
    return os.environ.get('FFMPEG_EXE','ffmpeg')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--preview',action='store_true'); args=ap.parse_args()
    if args.preview:
        sheet=Image.new('RGB',(1440,540))
        for j in range(6): sheet.paste(frame(j*10+5).resize((480,270)),((j%3)*480,(j//3)*270))
        sheet.save(ROOT/'contact_sheet.jpg'); frame(55).save(ROOT/'poster.jpg'); return
    cmd=[ffmpeg(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(ROOT/'silent.mp4')]
    with (ROOT/'render.log').open('w') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        for i in range(FPS*DURATION):
            proc.stdin.write(frame(i/FPS).tobytes())
            if i%300==0: print(f'Rendered {i/FPS:.0f}/60 seconds',flush=True)
        proc.stdin.close()
        if proc.wait(): raise RuntimeError('Video encoding failed; see render.log')

if __name__=='__main__': main()
