import re
from datetime import date, timedelta
import fitz
import streamlit as st

st.set_page_config(page_title='Escogido Pitch Report', page_icon='⚾', layout='wide')
NAVY=(0.052,0.14,0.26); BLUE=(0.10,0.25,0.43); RED=(0.78,0.10,0.17)
WHITE=(1,1,1); INK=(0.15,0.21,0.29); PALE=(0.94,0.96,0.98); GRAY=(0.42,0.48,0.54)
HEADERS=['Player','K','K-L','P','CS#','CS%','Miss#','Miss%','Foul#','Foul%','Total','Tot%','BIP','BIP%','1B','2B','3B','HR','TB','BABIP','SLG']
ANCHORS=[111.6,136.4,147,167.8,192.6,207.2,223.5,237.6,255.1,268,284.2,294.6,309.2,318.1,327.1,336,345.6,354.6,370.4,381.9]
SECTIONS=[('FASTBALL IN ZONE','main'),('FASTBALL CHASE BELOW ZONE','chase'),('FASTBALLS UP & IN · RHH','main'),('ALL PITCHES CHASE BELOW ZONE','chase'),('FASTBALLS UP & IN · LHH','main')]

def rows_in_band(page,y0,y1,x0,x1):
    words=[w for w in page.get_text('words') if y0 <= w[1] < y1 and x0 <= w[0] < x1]
    groups=[]
    for w in sorted(words,key=lambda a:(a[1],a[0])):
        if groups and abs(groups[-1][0][1]-w[1])<1.2:
            groups[-1].append(w)
        else: groups.append([w])
    return [sorted(g,key=lambda a:a[0]) for g in groups]

def parse_main(group):
    player=' '.join(w[4] for w in group if w[0]<104).strip()
    values=['']*20
    for w in group:
        if w[0]<104: continue
        idx=min(range(20),key=lambda i:abs(w[2]-ANCHORS[i]))
        if abs(w[2]-ANCHORS[idx])<5:
            values[idx]=w[4] if not values[idx] else values[idx]+' '+w[4]
    if not player or not values[2]: return None
    return [player]+values

def parse_chase(group):
    name=' '.join(w[4] for w in sorted(group,key=lambda w:w[0]) if w[0]<510).strip()
    metrics=[w[4] for w in sorted(group,key=lambda w:w[0]) if w[0]>=510]
    if len(metrics)!=3:return None
    pct,pitches,chase=metrics
    if not name or not re.fullmatch(r'\d+(?:\.\d+)?%',pct):return None
    if not(pitches.isdigit() and chase.isdigit()):return None
    if int(pitches)==0 or abs(float(pct[:-1])-100*int(chase)/int(pitches))>0.16:return None
    return [name,pct,pitches,chase]

def extract(pdf):
    doc=fitz.open(stream=pdf,filetype='pdf')
    if doc.page_count!=1:raise ValueError('Expected a one-page TrackMan export.')
    p=doc[0];t=p.get_text().lower()
    if not all(s in t for s in ['fastball in zone','fastballs up','chase']):
        raise ValueError('This is not the expected TrackMan report.')
    if abs(p.rect.width-612)>12 or abs(p.rect.height-792)>12:
        raise ValueError('Unexpected PDF page dimensions.')
    # Find CALCULATIONS and RESULTS positions in each column dynamically.
    words=p.get_text('words')
    def labels(xmin,xmax,label):
        return sorted(w[1] for w in words if xmin<w[0]<xmax and w[4].upper()==label)
    main_cal=labels(68,110,'CALCULATIONS')
    main_res=labels(68,110,'RESULTS')
    chase_cal=labels(425,475,'CALCULATIONS')
    chase_res=labels(425,475,'RESULTS')
    if not (len(main_cal)==len(main_res)==3 and len(chase_cal)==len(chase_res)==2):
        raise ValueError('Cannot locate the five expected table sections.')
    data=[]
    for ix,(title,kind) in enumerate(SECTIONS):
        k=(0 if ix==0 else 1 if ix==2 else 2) if kind=='main' else (0 if ix==1 else 1)
        cal=(main_cal if kind=='main' else chase_cal)[k]
        res=(main_res if kind=='main' else chase_res)[k]
        x0,x1=(65,390) if kind=='main' else (425,565)
        parser=parse_main if kind=='main' else parse_chase
        totals=[parser(g) for g in rows_in_band(p,cal+15,cal+26,x0,x1)]
        totals=[r for r in totals if r and r[0].upper()=='TOTAL']
        next_cal=(main_cal[k+1] if kind=='main' and k<2 else
                  chase_cal[k+1] if kind=='chase' and k<1 else p.rect.height-25)
        # Last main section can extend to footer; others stop before next panel.
        groups=rows_in_band(p,res+19,min(next_cal-3,p.rect.height-25),x0,x1)
        players=[parser(g) for g in groups]
        players=[r for r in players if r and r[0].upper()!='TOTAL']
        if len(totals)!=1 or not players:
            raise ValueError(f'{title}: could not identify totals and players.')
        if len({r[0].casefold() for r in players})!=len(players):
            raise ValueError(f'Duplicate player names detected in {title}.')
        if kind=='main':
            if any(len(r)!=21 or sum(bool(x) for x in r[1:])<18 for r in players):
                raise ValueError(f'Missing values in {title}.')
            # P is the third statistic; sum of player pitch counts should match the total.
            try:
                if sum(int(r[3]) for r in players)!=int(totals[0][3]):
                    raise ValueError(f'{title}: player pitch counts do not match total.')
            except (TypeError,ValueError) as e:
                raise ValueError(f'{title}: invalid pitch count: {e}')
        else:
            if sum(int(r[2]) for r in players)!=int(totals[0][2]) or sum(int(r[3]) for r in players)!=int(totals[0][3]):
                raise ValueError(f'{title}: Chase table totals do not match the players.')
        data.append((title,kind,totals[0],players))
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

def panel(page,x,y,w,h,title,kind,total,players):
    page.draw_rect(fitz.Rect(x,y,x+w,y+h),color=(.86,.89,.93),fill=WHITE,width=.6)
    page.draw_rect(fitz.Rect(x,y,x+w,y+27),color=NAVY,fill=NAVY)
    page.draw_rect(fitz.Rect(x,y,x+5,y+27),color=RED,fill=RED)
    write(page,x+14,y+18,title,10,WHITE,True)
    ncol=21 if kind=='main' else 4
    header_h=20
    table_top=y+27
    page.draw_rect(fitz.Rect(x+1,table_top,x+w-1,table_top+header_h),color=BLUE,fill=BLUE)
    if kind=='main':
        widths=[w*.177]+[w*.823/20]*20
        # Give the wider percentage columns slightly more space
        weights=[1,1.2,1.05,1.2,1.45,1.0,1.35,1.0,1.35,1.05,1.35,1.0,1.35,.85,.85,.85,.85,1.0,1.2,1.1]
        widths=[w*.18]+[w*.82*z/sum(weights) for z in weights]
        heads=HEADERS
    else:
        widths=[w*.57,w*.17,w*.12,w*.14]
        heads=['Player','Chase%','P','Chase#']
    edges=[x]
    for cw in widths:edges.append(edges[-1]+cw)
    for j,head in enumerate(heads):
        xx=edges[j]+3 if j==0 else edges[j+1]-3
        write(page,xx,table_top+13,head,5.5 if kind=='main' else 7,WHITE,True,'left' if j==0 else 'right',widths[j]-5)
    rows=[total]+players
    available=h-27-header_h-9
    rh=min(21 if kind=='chase' else 18,available/len(rows))
    for i,row in enumerate(rows):
        top=table_top+header_h+i*rh
        bg=(.87,.92,.97) if i==0 else (WHITE if i%2 else PALE)
        page.draw_rect(fitz.Rect(x+1,top,x+w-1,top+rh),color=None,fill=bg)
        if i==0: page.draw_rect(fitz.Rect(x+1,top,x+4,top+rh),color=None,fill=RED)
        for j,value in enumerate(row):
            xx=edges[j]+4 if j==0 else edges[j+1]-3
            font_sz=(7.7 if kind=='chase' else 6.1)
            if j==0: font_sz+=.2
            write(page,xx,top+rh*.70,value,font_sz,NAVY if i==0 else INK,i==0,'left' if j==0 else 'right',widths[j]-5)
    if table_top+header_h+len(rows)*rh>y+h-2:
        raise ValueError(f'{title} cannot fit on the page.')

def make_pdf(data,game_date,opponent):
    parsed=extract(data)
    main_need=sum(56+18*(len(parsed[i][3])+1) for i in (0,2,4))+20
    chase_need=sum(56+21*(len(parsed[i][3])+1) for i in (1,3))+12
    page_height=max(690,min(842,102+max(main_need,chase_need)+60))
    out=fitz.open(); page=out.new_page(width=1191,height=page_height)
    page.draw_rect(page.rect,color=None,fill=(.975,.980,.987))
    page.draw_rect(fitz.Rect(0,0,1191,11),color=None,fill=RED)
    write(page,28,48,'LEONES DEL ESCOGIDO',22,NAVY,True)
    write(page,28,71,'PITCH REPORT',13,RED,True)
    write(page,1160,49,f'{game_date:%B %d, %Y}  |  vs. {opponent}',11,GRAY,False,'right')
    page.draw_line((28,86),(1163,86),color=(.81,.84,.88),width=1)
    left_x,left_w=28,862
    right_x,right_w=904,259
    def needed_height(entry):
        _,kind,_,players=entry
        row_height=18 if kind=='main' else 21
        return 27+20+9+row_height*(len(players)+1)
    def stack(entries,x,w,y0,y_end,gap):
        heights=[needed_height(e) for e in entries]
        available=y_end-y0-gap*(len(entries)-1)
        if sum(heights)>available:
            # Scale row heights by available panel height when necessary.
            ratio=available/sum(heights)
            heights=[h*ratio for h in heights]
        cursor=y0
        for entry,h in zip(entries,heights):
            panel(page,x,cursor,w,h,*entry)
            cursor+=h+gap
    stack([parsed[0],parsed[2],parsed[4]],left_x,left_w,102,page_height-71,10)
    stack([parsed[1],parsed[3]],right_x,right_w,102,page_height-71,12)
    page.draw_line((28,page_height-54),(1163,page_height-54),color=(.81,.84,.88),width=1)
    write(page,28,page_height-37,'LEONES DEL ESCOGIDO  /  BASEBALL ANALYTICS',8,GRAY,True)
    write(page,1163,page_height-37,'1 / 1',8,GRAY,False,'right')
    pdf=out.tobytes(garbage=4,deflate=True)
    out.close();return pdf

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
