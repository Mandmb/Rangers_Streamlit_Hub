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
    """Read the same six report sections across one or multiple PDF pages.

    Source exports may switch between portrait and landscape. Each page is
    processed independently, then sections are assembled in report order.
    """
    doc = fitz.open(stream=pdf, filetype='pdf')
    try:
        if not 1 <= doc.page_count <= 20:
            raise ValueError('The uploaded PDF has an unexpected page count.')
        main_parts, side_parts = [], []
        for page_number, page in enumerate(doc, start=1):
            words = page.get_text('words')
            page_text = page.get_text().lower()
            if not page_text.strip():
                raise ValueError(f'Page {page_number} contains no selectable text.')

            def occurrences(term):
                return sorted(
                    (w for w in words if w[4].upper() == term),
                    key=lambda w:(w[1], w[0])
                )

            calculations = occurrences('CALCULATIONS')
            results = occurrences('RESULTS')
            if len(calculations) != len(results) or not calculations:
                raise ValueError(f'Page {page_number}: cannot identify table boundaries.')

            # Locate columns by the CALCULATIONS labels, which remain stable
            # even when page orientation and table widths change.
            xpos = sorted(w[0] for w in calculations)
            if len(xpos) < 2 or xpos[-1] - xpos[0] < page.rect.width * .25:
                raise ValueError(f'Page {page_number}: cannot distinguish table columns.')
            divide = (xpos[0] + xpos[-1]) / 2
            for side in ('main', 'side'):
                cals = sorted(
                    (w for w in calculations if (w[0] < divide) == (side == 'main')),
                    key=lambda w:w[1]
                )
                ress = sorted(
                    (w for w in results if (w[0] < divide) == (side == 'main')),
                    key=lambda w:w[1]
                )
                if len(cals) != len(ress):
                    raise ValueError(f'Page {page_number}: mismatched CALCULATIONS/RESULTS.')
                if side == 'main':
                    x0 = max(0, min(w[0] for w in cals)-18) if cals else 0
                    x1 = max(w[0] for w in calculations if w[0]>divide)-10
                else:
                    x0 = min(w[0] for w in cals)-8 if cals else divide
                    x1 = page.rect.width-8
                for i,(cal_word,res_word) in enumerate(zip(cals,ress)):
                    cal,res = cal_word[1],res_word[1]
                    if res <= cal:
                        raise ValueError(f'Page {page_number}: reversed section boundaries.')
                    next_cal = cals[i+1][1] if i+1<len(cals) else page.rect.height-18
                    if side == 'main':
                        header_words = [w[4] for w in words
                            if cal+8<=w[1]<=cal+17 and x0<=w[0]<x1]
                        has_first = '1st' in header_words and 'Looking' in header_words
                        has_avg = 'AVG' in header_words
                        headers = (['Player'] + (['1st P Looking'] if has_first else [])
                            + HEADERS[1:-1] + (['AVG'] if has_avg else []) + ['SLG'])
                        parser = lambda group, count=len(headers)-1: parse_main(group,count)
                    else:
                        # Third right-hand table, when present, is Fastball %.
                        k = len(side_parts)
                        kind = 'fastball' if k==2 else 'chase'
                        parser = parse_fastball if kind=='fastball' else parse_chase
                        headers = (['Player','P','Fastball%'] if kind=='fastball'
                                   else ['Player','Chase%','P','Chase#'])
                    totals = [parser(g) for g in rows_in_band(page,cal+17,res-1,x0,x1)]
                    totals = [r for r in totals if r and r[0].upper()=='TOTAL']
                    players = [parser(g) for g in rows_in_band(
                        page,res+17,min(next_cal-2,page.rect.height-13),x0,x1)]
                    players = [r for r in players if r and r[0].upper() not in ('TOTAL','PLAYER')]
                    if len(totals)!=1 or not players:
                        raise ValueError(
                            f'Page {page_number}: incomplete {side} table '
                            f'({len(totals)} totals, {len(players)} players).')
                    if len({r[0].casefold() for r in players}) != len(players):
                        raise ValueError(f'Page {page_number}: duplicate player names detected.')
                    record = (totals[0],players,headers,page_number)
                    (main_parts if side=='main' else side_parts).append(record)

        if len(main_parts)!=3 or len(side_parts) not in (2,3):
            raise ValueError(
                f'Expected three left-side tables and two or three right-side tables; '
                f'found {len(main_parts)} and {len(side_parts)} across {doc.page_count} pages.')

        assembled=[]
        main_titles=[SECTIONS[0][0],SECTIONS[2][0],SECTIONS[4][0]]
        side_titles=[SECTIONS[1][0],SECTIONS[3][0],SECTIONS[5][0]]
        for kind,records,titles in [('main',main_parts,main_titles),('side',side_parts,side_titles)]:
            for i,(total,players,headers,page_number) in enumerate(records):
                title=titles[i]
                category=('main' if kind=='main' else 'fastball' if i==2 else 'chase')
                if category=='main':
                    idx=headers.index('P')
                    if any(len(r)!=len(headers) for r in players):
                        raise ValueError(f'{title}: incomplete statistics.')
                    if sum(int(r[idx]) for r in players)!=int(total[idx]):
                        raise ValueError(f'{title}: pitch counts do not match the total.')
                elif category=='chase':
                    if (sum(int(r[2]) for r in players)!=int(total[2]) or
                        sum(int(r[3]) for r in players)!=int(total[3])):
                        raise ValueError(f'{title}: Chase counts do not match.')
                else:
                    if sum(int(r[1]) for r in players)!=int(total[1]):
                        raise ValueError(f'{title}: pitch totals do not match.')
                assembled.append((title,category,total,players,headers))
        # Return in original visual report order.
        lookup={record[0]:record for record in assembled}
        return [lookup[t] for t,k in SECTIONS if t in lookup]
    finally:
        doc.close()

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
st.caption('Pitch Report v2.1 | Multi-page input → single-page output')
st.write('Upload the TrackMan export to generate a professionally redesigned, single-page PDF with unchanged statistics.')
uploaded=st.file_uploader('Upload TrackMan PDF',type=['pdf'])
if uploaded is not None:
    try:
        with fitz.open(stream=uploaded.getvalue(), filetype='pdf') as src:
            st.info(f'Source PDF detected: {src.page_count} page(s). Output will be one page.')
    except Exception as e:
        st.error(f'Cannot open PDF: {e}')
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
