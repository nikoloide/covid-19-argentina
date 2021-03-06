import pandas as pd
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime
import re
from collections import Counter
from unidecode import unidecode
import PyPDF2 

date_pat = re.compile('(\d+-\d+-\d+)')

provinces = [
    'Ciudad Autonoma de Buenos Aires', 'Provincia de Buenos Aires', 'Catamarca', 'Chaco', 'Chubut', 'Córdoba', 'Corrientes', 'Entre Ríos',
    'Formosa', 'Jujuy', 'La Pampa', 'La Rioja', 'Mendoza', 'Misiones', 'Neuquén', 'Río Negro',
    'Salta', 'San Juan', 'San Luis', 'Santa Cruz', 'Santa Fe', 'Santiago del Estero', 'Tierra del Fuego','Tucumán'
]

headers = {'authority': 'www.argentina.gob.ar',
 'cache-control': 'max-age=0',
 'dnt': '1',
 'upgrade-insecure-requests': '1',
 'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36',
 'sec-fetch-dest': 'document',
 'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
 'sec-fetch-site': 'none',
 'sec-fetch-mode': 'navigate',
 'sec-fetch-user': '?1',
 'accept-language': 'en-US,en;q=0.9,es-AR;q=0.8,es;q=0.7'}


def get_pdf_links():
    content = requests.get('https://www.argentina.gob.ar/coronavirus/informe-diario', headers=headers).content

    soup = BeautifulSoup(content, 'html.parser')

    pdfs = []
    for a in soup.find_all('a'):
        href = a.attrs.get('href', '')
        if 'facebook' in href: continue
        if 'linkedin' in href: continue
        if 'whatsapp' in href: continue
        if 'matutino' in href: continue
            
        if 'pdf' in href:
            pdfs.append(href)

    return pdfs


def fetch_pdf(link):
    cache_path = Path('cache')
    cache_path.mkdir(exist_ok=True, parents=True)
    cache_fname = cache_path / link.split('/')[-1]
    if not cache_fname.exists():
        pdf_content = requests.get(link, headers=headers).content
        with cache_fname.open('wb') as f: f.write(pdf_content)
    return cache_fname


def extract_date(link):
    last = link.split('/')[-1]

    match = date_pat.search(last)
    if match is None: return
    date_string = match.group(0)

    day, month, year = map(int, date_string.split('-'))
    if year == 20: year = 2020
    return datetime(year, month, day)


def get_vec(s):
    res = Counter(s)
    res.update(f'{prev}_{next}' for prev, next in zip(s[:-1], s[1:]))
    return res


def sim(query_s, target_s):
    query_v = get_vec(query_s.lower())
    target_v = get_vec(target_s.lower())
    
    res = 0
    for char, cnt in query_v.items():
        res += min(cnt, target_v.get(char, 0))
    return res / max(sum(target_v.values()), sum(query_v.values()))
    
def infer_province(txt):
    if 'buenosaires' in txt.lower().replace(' ', ''):
        if 'ciudad' in txt.lower(): return 'Ciudad autonoma de Buenos Aires', 1
        else: return 'Provincia de Buenos Aires', 1
                      
    scores = {}
    txt = unidecode(txt.lower())
    for p in provinces:
        scores[p] = sim(txt, unidecode(p.lower()))
    
    p, score = max(scores.items(), key=lambda x: x[1])
    if p == 'Buenos Aires': p = 'Provincia de Buenos Aires'
    return p, score
    

def extract_pdf_data(cached_fname):
    print(f"Processing {cached_fname}...")
    pat = re.compile(r'[^/|\w](?P<num>\d+)(?P<middle>( *[a-z]{,3}){,2} *)(?P<place>[A-Z]\w+(\s\w+)*)')
    pat2 = re.compile('\((?P<num>\d+)\)(?P<middle>( *[a-z]{,3}){,5} *)(?P<place>[A-Z]\w+(\s\w+)*)')
    pat3 = re.compile('-\s+(?P<place>[A-Z]\w+(\s\w+)*)(?P<middle>\s+)(?P<num>\d+)\s+\|\s+(?P<acum>\d+)')

    pdfReader = PyPDF2.PdfFileReader(cached_fname.open('rb'))
    pdfReader.getPage(0)
    txt = '\n\n'.join(
        page.extractText().replace('personas', '').replace('\n', ' ') for page in pdfReader.flattenedPages
    )

    matches = list(pat.finditer(txt)) + list(pat2.finditer(txt)) + list(pat3.finditer(txt))
    print(f"\tHas {len(matches)} matches")

    res = []
    for e in matches:
        gd = e.groupdict()
        
        if 'argentina' in gd['place'].lower(): continue 
        if 'covid' in gd['place'].lower(): continue
        if 'informe' in gd['place'].lower(): continue
        
        gd['infered_place'], gd['infered_place_score'] = infer_province(gd['place'])
        
        gd['infected'] = int(gd.pop('num'))
        if gd['infected'] == 0: continue
        res.append(gd)
    return res


def get_arg_df():
    docs = []

    for pdf_link in get_pdf_links():
        date = extract_date(pdf_link)
        if date is None: 
            print(f'Skipping {pdf_link.split("/")[-1]}')
            continue

        cached_fname = fetch_pdf(pdf_link) 
        for doc in extract_pdf_data(cached_fname):
            doc.pop('middle')
            doc['date'] = date
            docs.append(doc)


    raw_df = pd.DataFrame(docs).sort_values('date')
    dfs = []

    for place in raw_df.infered_place.unique():
        p_df = raw_df[raw_df.infered_place==place].copy()
        d0 = p_df.date.min()
        p_df['days_from_first_infection'] = (p_df.date - d0).apply(lambda x: x.days)
        p_df['cum_infected'] = p_df['infected'].cumsum()
        dfs.append(p_df)
        
    return pd.concat(dfs)

