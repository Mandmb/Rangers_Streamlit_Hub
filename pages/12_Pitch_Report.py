import re
from datetime import date, timedelta
import fitz
import streamlit as st

st.set_page_config(page_title='Escogido Pitch Report', page_icon='⚾', layout='wide')
NAVY=(0.052,0.14,0.26); BLUE=(0.10,0.25,0.43); RED=(0.78,0.10,0.17)
WHITE=(1,1,1); INK=(0.15,0.21,0.29); PALE=(0.94,0.96,0.98); GRAY=(0.42,0.48,0.54)
HEADERS=['Player','K','K-L','P','CS#','CS%','Miss#','Miss%','Foul#','Foul%','Total','Tot%','BIP','BIP%','1B','2B','3B','HR','TB','BABIP','SLG']
ANCHORS=[111.6,136.4,147,167.8,192.6,207.2,223.5,237.6,255.1,268,284.2,294.6,309.2,318.1,327.1,336,345.6,354.6,370.4,381.9]
SECTIONS=[('FASTBALL IN ZONE','main'),('FASTBALL CHASE BELOW ZONE','chase'),('FASTBALLS UP & IN · RHH','main'),('ALL PITCHES CHASE BELOW ZONE','chase'),('FASTBALLS UP & IN · LHH','main'),('FASTBALL %','fastball')]

def rows_in_band(page,y0,y1,x0,x1):
    words=[w for w in page.get_text('words') if y0 <= w[1] < y1 and x0 <= w[0] < x1]
    groups=[]
    for w in sorted(words,key=lambda a:(a[1],a[0])):
        if groups and abs(groups[-1][0][1]-w[1])<1.2:
            groups[-1].append(w)
        else: groups.append([w])
    return [sorted(g,key=lambda a:a[0]) for g in groups]

def parse_main(group, stat_count=20):
    # Parse data from the RIGHT: every main-table row has precisely 20
    # statistics, while player names can contain any number of words.
    # This avoids assuming the same column coordinates in every export.
    tokens=[w[4] for w in sorted(group,key=lambda w:w[0])]
    if len(tokens)<stat_count+1:
        return None
    values=tokens[-stat_count:]
    player=' '.join(tokens[:-stat_count]).strip()
    numeric=re.compile(r'(?:- | -|\d+(?:\.\d+)?%?|\.\d+|-)'.strip())
    if not player or not all(numeric.fullmatch(v) for v in values):
        return None
    if player.upper() in ('PLAYER','CALCULATIONS','RESULTS'):
        return None
    return [player]+values

def parse_chase(group):
    tokens=[w[4] for w in sorted(group,key=lambda w:w[0])]
    if len(tokens)<4: return None
    player=' '.join(tokens[:-3]).strip()
    pct,pitches,chase=tokens[-3:]
    if not player or not re.fullmatch(r'\d+(?:\.\d+)?%',pct): return None
    if not(pitches.isdigit() and chase.isdigit()): return None
    if int(pitches)==0 or abs(float(pct[:-1])-100*int(chase)/int(pitches))>.16:return None
    return [player,pct,pitches,chase]

def parse_fastball(group):
    tokens=[w[4] for w in sorted(group,key=lambda w:w[0])]
    if len(tokens)<3:return None
    player=' '.join(tokens[:-2]).strip()
    pitches,pct=tokens[-2:]
    if not player or not pitches.isdigit() or not re.fullmatch(r'\d+(?:\.\d+)?%',pct):return None
    return [player,pitches,pct]

def extract(pdf):
    doc=fitz.open(stream=pdf,filetype='pdf')
    if doc.page_count!=1:raise ValueError('Expected a one-page TrackMan export.')
    p=doc[0]
    if abs(p.rect.width-612)>12 or abs(p.rect.height-792)>12:
        raise ValueError('Unexpected PDF page dimensions.')
    words=p.get_text('words')
    text=p.get_text().lower()
    if not all(t in text for t in ('fastball in zone','chase','fastballs up')):
        raise ValueError('Expected Escogido TrackMan tables not found.')
    def labels(xmin,xmax,label):
        return sorted(w[1] for w in words if xmin<w[0]<xmax and w[4].upper()==label)
    main_cal=labels(45,190,'CALCULATIONS')
    main_res=labels(45,190,'RESULTS')
    side_cal=labels(420,475,'CALCULATIONS')
    side_res=labels(420,475,'RESULTS')
    if len(main_cal)!=3 or len(main_res)!=3 or len(side_cal)!=len(side_res) or len(side_cal) not in (2,3):
        raise ValueError('Cannot identify required TrackMan report sections.')
    data=[]
    for ix,(title,kind) in enumerate(SECTIONS):
        if kind=='fastball' and len(side_cal)==2:
            continue  # backwards compatibility with older PDF exports
        if kind=='main':
            k={0:0,2:1,4:2}[ix]
            cal,res=main_cal[k],main_res[k]
            x0,x1=45,410
            next_cal=main_cal[k+1] if k<2 else p.rect.height-25
            header_words=[w[4] for w in words if cal+8<=w[1]<=cal+14 and 45<w[0]<410]
            has_first=('1st' in header_words and 'Looking' in header_words)
            has_avg=('AVG' in header_words)
            headers=['Player']+(['1st P Looking'] if has_first else [])+HEADERS[1:-1]+(['AVG'] if has_avg else [])+['SLG']
            parser=lambda g:parse_main(g,len(headers)-1)
        else:
            k=0 if ix==1 else 1 if ix==3 else 2
            cal,res=side_cal[k],side_res[k]
            x0,x1=425,572
            next_cal=side_cal[k+1] if k<len(side_cal)-1 else p.rect.height-24
            parser=parse_chase if kind=='chase' else parse_fastball
            headers=['Player','Chase%','P','Chase#'] if kind=='chase' else ['Player','P','Fastball%']
        total_rows=[parser(g) for g in rows_in_band(p,cal+17,res-1,x0,x1)]
        total_rows=[r for r in total_rows if r and r[0].upper()=='TOTAL']
        players=[parser(g) for g in rows_in_band(p,res+17,min(next_cal-2,p.rect.height-20),x0,x1)]
        players=[r for r in players if r and r[0].upper()!='TOTAL' and r[0].upper()!='PLAYER']
        if len(total_rows)!=1 or not players:
            raise ValueError(f'{title}: expected a totals row and player rows; extracted {len(total_rows)} totals and {len(players)} players.')
        total=total_rows[0]
        if len({r[0].casefold() for r in players})!=len(players):
            raise ValueError(f'{title}: duplicate player rows found.')
        if kind=='main':
            pitch_idx=headers.index('P')
            if any(len(r)!=len(headers) for r in players):
                raise ValueError(f'{title}: incomplete stat columns.')
            if sum(int(r[pitch_idx]) for r in players)!=int(total[pitch_idx]):
                raise ValueError(f'{title}: pitch counts do not match the total.')
        elif kind=='chase':
            if sum(int(r[2]) for r in players)!=int(total[2]) or sum(int(r[3]) for r in players)!=int(total[3]):
                raise ValueError(f'{title}: Chase totals do not match player data.')
        else:
            if sum(int(r[1]) for r in players)!=int(total[1]):
                raise ValueError(f'{title}: Fastball % pitch totals do not match player data.')
        data.append((title,kind,total,players,headers))
    doc.close()
    return data

def write(page,x,y,value,sz=8,color=INK,bold=False,align='left',limit=None):
    font='hebo' if bold else 'helv'
    s=str(value)
    if limit:
        while fitz.get_text_length(s,fontname=font,fontsize=sz)>limit and sz>4.5: sz-=.2
    width=fitz.get_text_length(s,fontname=font,fontsize=sz)
    if align=='right':x-=width
    page.insert_text((x,y),s,fontname=font,fontsize=sz,color=color)

def panel(page,x,y,w,h,title,kind,total,players,headers):
    page.draw_rect(fitz.Rect(x,y,x+w,y+h),color=(.86,.89,.93),fill=WHITE,width=.6)
    page.draw_rect(fitz.Rect(x,y,x+w,y+26),color=NAVY,fill=NAVY)
    page.draw_rect(fitz.Rect(x,y,x+5,y+26),color=RED,fill=RED)
    write(page,x+13,y+17,title,10,WHITE,True,limit=w-22)
    head_h=19; table_top=y+26
    page.draw_rect(fitz.Rect(x+1,table_top,x+w-1,table_top+head_h),color=BLUE,fill=BLUE)
    if kind=='main':
        weights=[]
        for head in headers[1:]:
            weights.append(1.7 if head=='1st P Looking' else 1.5 if head in ('CS%','Miss%','Foul%','Tot%','BIP%','BABIP','AVG','SLG') else 1.2 if head in ('CS#','Miss#','Foul#','Total','BIP') else 1.0)
        widths=[w*.18]+[w*.82*z/sum(weights) for z in weights]
    elif kind=='chase':widths=[w*.55,w*.19,w*.12,w*.14]
    else:widths=[w*.58,w*.18,w*.24]
    edges=[x]
    for cw in widths:edges.append(edges[-1]+cw)
    for j,head in enumerate(headers):
        xx=edges[j]+3 if j==0 else edges[j+1]-3
        write(page,xx,table_top+13,head,5.6 if kind=='main' else 7.2,WHITE,True,'left' if j==0 else 'right',widths[j]-5)
    rows=[total]+players
    rh=(h-26-head_h-5)/len(rows)
    for i,row in enumerate(rows):
        top=table_top+head_h+i*rh
        bg=(.87,.92,.97) if i==0 else (WHITE if i%2 else PALE)
        page.draw_rect(fitz.Rect(x+1,top,x+w-1,top+rh),color=None,fill=bg)
        if i==0:page.draw_rect(fitz.Rect(x+1,top,x+4,top+rh),color=None,fill=RED)
        for j,value in enumerate(row):
            xx=edges[j]+4 if j==0 else edges[j+1]-3
            size=(7.3 if kind!='main' else 6.1)
            if rh<13:size=min(size,5.8 if kind=='main' else 6.8)
            if j==0:size+=.15
            write(page,xx,top+rh*.72,value,size,NAVY if i==0 else INK,i==0,'left' if j==0 else 'right',widths[j]-5)

def make_pdf(data,game_date,opponent):
    parsed=extract(data)
    left=[e for e in parsed if e[1]=='main']
    right=[e for e in parsed if e[1]!='main']
    # Taller landscape page when the source contains many player rows.
    def height_for(entries):
        return sum(50+(15 if e[1]=='main' else 16)*(len(e[3])+1) for e in entries)+12*(len(entries)-1)
    usable=max(height_for(left),height_for(right))
    height=max(700,min(1250,155+usable))
    out=fitz.open(); page=out.new_page(width=1191,height=height)
    page.draw_rect(page.rect,color=None,fill=(.975,.980,.987))
    page.draw_rect(fitz.Rect(0,0,1191,10),color=None,fill=RED)
    write(page,28,46,'LEONES DEL ESCOGIDO',22,NAVY,True)
    write(page,28,69,'PITCH REPORT',13,RED,True)
    write(page,1160,48,f'{game_date:%B %d, %Y}  |  vs. {opponent}',11,GRAY,False,'right')
    page.draw_line((28,86),(1163,86),color=(.81,.84,.88),width=1)
    def stack(entries,x,w):
        if not entries:return
        y0=101; y_end=height-65; gap=12
        available=y_end-y0-gap*(len(entries)-1)
        ideal=[50+(15 if e[1]=='main' else 16)*(len(e[3])+1) for e in entries]
        ratio=(available/sum(ideal)) if entries[0][1]=='main' else min(1,available/sum(ideal))
        ys=[max(45+10*(len(e[3])+1),v*ratio) for e,v in zip(entries,ideal)]
        if sum(ys)>available:ys=[v*available/sum(ys) for v in ys]
        cursor=y0
        for entry,h in zip(entries,ys):
            panel(page,x,cursor,w,h,*entry)
            cursor+=h+gap
    stack(left,28,862)
    stack(right,904,259)
    page.draw_line((28,height-51),(1163,height-51),color=(.81,.84,.88),width=1)
    write(page,28,height-34,'LEONES DEL ESCOGIDO  /  BASEBALL ANALYTICS',8,GRAY,True)
    write(page,1163,height-34,'1 / 1',8,GRAY,False,'right')
    result=out.tobytes(garbage=4,deflate=True)
    out.close()
    return result

st.title('⚾ Leones del Escogido - Pitch Report')
st.write('Upload the TrackMan export to generate a professionally redesigned, single-page PDF with unchanged statistics.')
uploaded=st.file_uploader('Upload TrackMan PDF',type=['pdf'])
c1,c2=st.columns(2)
with c1: game_date=st.date_input('Game Date',value=date.today()-timedelta(days=1),format='MM/DD/YYYY')
with c2: opponent=st.text_input('Opponent',placeholder='Toros del Este')
if st.button('Generate Pitch Report',type='primary',use_container_width=True):
    if not uploaded or not opponent.strip(): st.warning('Upload the PDF and enter the opponent.')
    else:
        try:
            result=make_pdf(uploaded.getvalue(),game_date,opponent.strip())
            st.session_state['escogido_report']=(uploaded.getvalue(),game_date,opponent.strip(),result)
            st.success('Your one-page report is ready.')
        except Exception as exc: st.error(f'Could not generate report: {exc}')
if uploaded and 'escogido_report' in st.session_state:
    original,dt,opp,result=st.session_state['escogido_report']
    if (original,dt,opp)==(uploaded.getvalue(),game_date,opponent.strip()):
        safe=re.sub(r'[^A-Za-z0-9_-]+','_',opp)
        st.download_button('⬇️ Download Pitch Report PDF',result,file_name=f'Escogido_Pitch_Report_{dt:%Y-%m-%d}_{safe}.pdf',mime='application/pdf',type='primary',use_container_width=True)
