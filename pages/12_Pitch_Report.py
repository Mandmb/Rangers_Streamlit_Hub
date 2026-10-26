import re
from datetime import date, timedelta
import fitz
import streamlit as st

st.set_page_config(page_title='Escogido Pitch Report', page_icon='⚾', layout='wide')
NAVY=(0.052,0.14,0.26); BLUE=(0.10,0.25,0.43); RED=(0.78,0.10,0.17)
WHITE=(1,1,1); INK=(0.15,0.21,0.29); PALE=(0.94,0.96,0.98); GRAY=(0.42,0.48,0.54)
HEADERS=['Player','K','K-L','P','CS#','CS%','Miss#','Miss%','Foul#','Foul%','Total','Tot%','BIP','BIP%','1B','2B','3B','HR','TB','BABIP','SLG']
ANCHORS=[111.6,136.4,147,167.8,192.6,207.2,223.5,237.6,255.1,268,284.2,294.6,309.2,318.1,327.1,336,345.6,354.6,370.4,381.9]
SECTIONS=[('FASTBALL IN ZONE','main',80,110,270),('FASTBALL CHASE BELOW ZONE','chase',80,110,260),('FASTBALLS UP & IN · RHH','main',418,448,570),('ALL PITCHES CHASE BELOW ZONE','chase',432,462,591),('FASTBALLS UP & IN · LHH','main',620,649,728)]

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
    player=' '.join(w[4] for w in group if 429<w[0]<513).strip()
    vals=[w[4] for w in group if w[0]>=513]
    if not player or len(vals)!=3: return None
    return [player]+vals

def extract(pdf):
    doc=fitz.open(stream=pdf,filetype='pdf')
    if doc.page_count!=1: raise ValueError('Expected a one-page TrackMan export.')
    p=doc[0]; text=p.get_text().lower()
    if not all(s in text for s in ['fastball in zone','fastballs up','chase']):
        raise ValueError('The uploaded report does not match the expected format.')
    if abs(p.rect.width-612)>12 or abs(p.rect.height-792)>12:
        raise ValueError('Unexpected source PDF page dimensions.')
    data=[]
    for title,kind,total_y,start,end in SECTIONS:
        left,right=(65,390) if kind=='main' else (425,565)
        parser=parse_main if kind=='main' else parse_chase
        total_rows=[parser(g) for g in rows_in_band(p,total_y,total_y+8,left,right)]
        total_rows=[r for r in total_rows if r and r[0]=='TOTAL']
        players=[parser(g) for g in rows_in_band(p,start,end,left,right)]
        players=[r for r in players if r and r[0] != 'TOTAL']
        minimum=6 if ('LHH' in title) else 11
        if len(total_rows)!=1 or len(players)<minimum:
            raise ValueError(f'Could not reliably extract {title}: {len(total_rows)} totals and {len(players)} player rows.')
        if kind=='main' and any(sum(bool(x) for x in r[1:])<18 for r in players):
            raise ValueError(f'Missing statistics in {title}; please check the original PDF format.')
        data.append((title,kind,total_rows[0],players))
    doc.close(); return data

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
    out=fitz.open(); page=out.new_page(width=1191,height=842)
    page.draw_rect(page.rect,color=None,fill=(.975,.980,.987))
    page.draw_rect(fitz.Rect(0,0,1191,11),color=None,fill=RED)
    write(page,28,48,'LEONES DEL ESCOGIDO',22,NAVY,True)
    write(page,28,71,'PITCH REPORT',13,RED,True)
    write(page,1160,49,f'{game_date:%B %d, %Y}  |  vs. {opponent}',11,GRAY,False,'right')
    page.draw_line((28,86),(1163,86),color=(.81,.84,.88),width=1)
    # Space-efficient grid, three full-width stat tables and two chase tables
    left_x,left_w=28,862
    right_x,right_w=904,259
    specs=[(left_x,100,left_w,288),(right_x,100,right_w,288),(left_x,402,left_w,195),(right_x,402,right_w,355),(left_x,611,left_w,146)]
    for entry,spec in zip(parsed,specs): panel(page,*spec,*entry)
    page.draw_line((28,788),(1163,788),color=(.81,.84,.88),width=1)
    write(page,28,805,'LEONES DEL ESCOGIDO  /  BASEBALL ANALYTICS',8,GRAY,True)
    write(page,1163,805,'1 / 1',8,GRAY,False,'right')
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
