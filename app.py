import os
import re
import time
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
import streamlit as st

DOWNLOAD_DIR = "igc_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

st.set_page_config(page_title="Soaring IGC Downloader", layout="wide")
st.title("Soaring IGC Downloader")
st.markdown("Paste a SoaringSpot page URL. Only explicit .igc and download endpoints will be fetched.")

url = st.text_input("SoaringSpot URL", "https://www.soaringspot.com/en_gb/...")
contest_mode = st.checkbox("Download entire contest (classes & days)")
use_api = st.checkbox("Use SoaringSpot API when available")
api_token = None
if use_api:
    api_token = st.text_input("API token (optional)")
download = st.button("Download IGCs")


def sanitize(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"[^A-Za-z0-9 _-]", "_", str(name)).strip()[:150]


def save_stream(r, out_dir):
    cd = r.headers.get('content-disposition', '')
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        name = m.group(1)
    else:
        name = os.path.basename(urlparse(r.url).path) or f'flight_{int(time.time())}.igc'
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, 'wb') as fh:
        for chunk in r.iter_content(64 * 1024):
            if chunk:
                fh.write(chunk)
    return path


def find_candidates(html, base):
    s = BeautifulSoup(html, "html.parser")
    candidates = set()
    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        lower = href.lower()
        if lower.endswith(".igc") or "download-contest-flight" in lower or "download-flight" in lower or "/download/" in lower:
            candidates.add(href if href.startswith("http") else urljoin(base, href))
    # scan attributes for embedded href fragments (menu popups etc)
    for tag in s.find_all(True):
        for val in tag.attrs.values():
            txt = " ".join(val) if isinstance(val, (list, tuple)) else str(val)
            for m in re.findall(r'href=["\']([^"\']+)["\']', txt):
                if any(k in m.lower() for k in ('.igc', 'download-contest-flight', 'download-flight', '/download/')):
                    candidates.add(m if m.startswith('http') else urljoin(base, m))
    return sorted(candidates)


def find_class_pages_from_contest(html, base):
    s = BeautifulSoup(html, "html.parser")
    classes = []
    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text() or "").strip()
        if not href:
            continue
        if any(p in href for p in ("/classes/", "/results/", "/class/")):
            cls_name = text or href.split('/')[-1]
            url_abs = href if href.startswith('http') else urljoin(base, href)
            classes.append((sanitize(cls_name), url_abs))
    # dedupe preserving order
    seen = set(); out = []
    for n, u in classes:
        if u in seen: continue
        seen.add(u); out.append((n, u))
    return out


def parse_day_from_text(text: str):
    if not text:
        return None
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2}[\/.]\d{1,2}[\/.]20\d{2})", text)
    if m:
        s = m.group(1).replace('.', '/').replace('-', '/')
        parts = s.split('/')
        if len(parts) == 3:
            d, mo, y = parts
            try:
                return f"{y}-{int(mo):02d}-{int(d):02d}"
            except Exception:
                pass
    m = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+20\d{2})", text)
    if m:
        return sanitize(m.group(1))
    m = re.search(r"([A-Za-z]+\s+\d{1,2},\s*20\d{2})", text)
    if m:
        return sanitize(m.group(1))
    return None


def extract_day_from_page(html: str, url: str):
    s = BeautifulSoup(html, 'html.parser')
    for h in ['h1', 'h2', 'h3', 'h4']:
        for el in s.find_all(h):
            txt = (el.get_text() or '').strip()
            d = parse_day_from_text(txt)
            if d:
                return d
    for el in s.find_all(attrs={'class': True}):
        cls = ' '.join(el.get('class'))
        if 'date' in cls.lower() or 'day' in cls.lower():
            d = parse_day_from_text(el.get_text() or '')
            if d:
                return d
    for el in s.find_all(attrs={'id': True}):
        iid = el.get('id')
        if 'date' in iid.lower() or 'day' in iid.lower():
            d = parse_day_from_text(el.get_text() or '')
            if d:
                return d
    p = urlparse(url)
    seg = p.path.rstrip('/').split('/')[-1]
    d = parse_day_from_text(seg)
    if d:
        return d
    return 'day'


def format_task_date(val):
    if not val:
        return None
    if isinstance(val, str):
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", val)
        if m:
            return m.group(1)
        d = parse_day_from_text(val)
        if d:
            return d
        return sanitize(val)
    return None


def canonical_url(u):
    p = urlparse(u)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.pop('dl', None)
    query = urlencode(sorted(q.items())) if q else ''
    return urlunparse((p.scheme, p.netloc, p.path, p.params, query, p.fragment))


# Contest-mode UI & download (runs independently so the multiselect doesn't disappear on rerun)
if contest_mode:
    if not url or 'soaringspot.com' not in url:
        st.info('Enter a valid SoaringSpot contest URL to discover classes.')
    else:
        sess = requests.Session()
        sess.headers.update({'User-Agent': 'Mozilla/5.0'})
        try:
            resp = sess.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            st.error(f'Fetch failed: {e}')
            resp = None

        if resp:
            base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            # Discover classes via API (if asked) then HTML fallback and show selection UI
            st.info('Discovering classes...')
            contest_name = sanitize(urlparse(url).path.split('/')[-2] if '/' in urlparse(url).path else 'contest')
            api_classes = {}
            html_classes = {}
            class_names = []

            if use_api and api_token:
                try:
                    parts = [p for p in urlparse(url).path.split('/') if p]
                    slug = parts[-1] if parts else None
                    headers = {'Authorization': f'Bearer {api_token}'}
                    q = {'slug': slug} if slug else {}
                    cresp = sess.get('https://api.soaringspot.com/v1/contests', params=q, headers=headers, timeout=10)
                    cresp.raise_for_status()
                    items = cresp.json()
                    if isinstance(items, dict) and items.get('data'):
                        items = items['data']
                    contest = items[0]
                    contest_name = sanitize(contest.get('name') or contest.get('title') or slug or contest_name)
                    contest_id = contest.get('id') or contest.get('contest_id')
                    cresp = sess.get(f'https://api.soaringspot.com/v1/contests/{contest_id}/classes', headers=headers, timeout=10)
                    if cresp.ok:
                        cdata = cresp.json()
                        if isinstance(cdata, dict) and cdata.get('data'):
                            cdata = cdata['data']
                        for cls in cdata:
                            cls_name = sanitize(cls.get('name') or cls.get('title') or str(cls.get('id')))
                            cls_id = cls.get('id')
                            api_classes[cls_name] = {'id': cls_id, 'name': cls_name}
                            class_names.append(cls_name)
                except Exception as e:
                    st.warning(f'API class discovery failed: {e}')

            # HTML fallback
            class_pages = find_class_pages_from_contest(resp.text, base)
            for n, u in class_pages:
                if n not in class_names:
                    class_names.append(n)
                html_classes[n] = u

            class_names = sorted(set(class_names))
            if not class_names:
                st.info('No classes found on contest page.')
            else:
                st.write('Discovered classes:')
                st.write(class_names)
                selected = st.multiselect('Select classes to download', options=class_names, default=class_names)
                if st.button('Download selected classes', key='download_selected') and selected:
                    all_links = []
                    # API-selected
                    if use_api and api_token and api_classes:
                        headers = {'Authorization': f'Bearer {api_token}'}
                        for name in selected:
                            if name in api_classes:
                                cls_id = api_classes[name]['id']
                                cls_name = api_classes[name]['name']
                                try:
                                    tresp = sess.get(f'https://api.soaringspot.com/v1/classes/{cls_id}/tasks', headers=headers, timeout=10)
                                    if not tresp.ok:
                                        continue
                                    tdata = tresp.json()
                                    if isinstance(tdata, dict) and tdata.get('data'):
                                        tdata = tdata['data']
                                    for t in tdata:
                                        task_id = t.get('id')
                                        tdate = format_task_date(t.get('date') or t.get('start_date') or t.get('task_date') or t.get('name') or '') or 'day'
                                        results_resp = sess.get(f'https://api.soaringspot.com/v1/tasks/{task_id}/results', headers=headers, timeout=10)
                                        if not results_resp.ok:
                                            continue
                                        rdata = results_resp.json()
                                        if isinstance(rdata, dict) and rdata.get('data'):
                                            rdata = rdata['data']
                                        for ritem in rdata:
                                            flight_id = None
                                            if isinstance(ritem, dict):
                                                flight_id = ritem.get('flight_id') or (ritem.get('flight') or {}).get('id')
                                            if flight_id:
                                                fresp = sess.get(f'https://api.soaringspot.com/v1/flights/{flight_id}', headers=headers, timeout=10)
                                                if fresp.ok:
                                                    try:
                                                        fj = fresp.json()
                                                        download_url = fj.get('download') or fj.get('download_url') or fj.get('url')
                                                        if download_url:
                                                            all_links.append((download_url, contest_name, cls_name, tdate))
                                                        else:
                                                            all_links.append((urljoin(base, f"/en_gb/download-contest-flight/{contest_id}-{flight_id}?dl=1"), contest_name, cls_name, tdate))
                                                    except Exception:
                                                        all_links.append((f'https://api.soaringspot.com/v1/flights/{flight_id}', contest_name, cls_name, tdate))
                                except Exception:
                                    continue

                    # HTML-selected
                    for name in selected:
                        if name in html_classes and name not in api_classes:
                            cls_url = html_classes[name]
                            try:
                                cr = sess.get(cls_url, timeout=12); cr.raise_for_status()
                                cls_soup = BeautifulSoup(cr.text, 'html.parser')
                                found_daily = []
                                for a in cls_soup.find_all('a', href=True):
                                    href = a['href']
                                    if '/daily' in href or ('/results/' in href and 'task' in href):
                                        found_daily.append(href if href.startswith('http') else urljoin(base, href))
                                if found_daily:
                                    for dl in found_daily:
                                        try:
                                            dr = sess.get(dl, timeout=12); dr.raise_for_status()
                                            day = extract_day_from_page(dr.text, dl) or sanitize(dl.rstrip('/').split('/')[-1])
                                            for link in find_candidates(dr.text, base):
                                                all_links.append((link, contest_name, name, day))
                                        except Exception:
                                            continue
                                else:
                                    page_day = extract_day_from_page(cr.text, cls_url) or 'all'
                                    for link in find_candidates(cr.text, base):
                                        all_links.append((link, contest_name, name, page_day))
                            except Exception:
                                continue

                    # dedupe and download
                    seen = set(); final = []
                    for link, c_name, cls_name, day in all_links:
                        key = canonical_url(link)
                        if key in seen: continue
                        seen.add(key); final.append((link, c_name, cls_name, day))

                    prog = st.progress(0); rows = []
                    for i, (link, c_name, cls_name, day) in enumerate(final, 1):
                        fetch = link
                        if '/download-contest-flight/' in link and 'dl=' not in link:
                            fetch = link + ('&dl=1' if '?' in link else '?dl=1')
                        try:
                            hdrs = sess.headers.copy(); hdrs.update({'Referer': url, 'Accept': 'application/vnd.flight+igc,application/octet-stream,*/*'})
                            r = sess.get(fetch, stream=True, timeout=30, headers=hdrs)
                            ctype = r.headers.get('content-type','').lower()
                            if r.status_code==200 and ('.igc' in ctype or 'flight' in ctype or 'content-disposition' in r.headers or fetch.lower().endswith('.igc')):
                                out_dir = os.path.join(DOWNLOAD_DIR, sanitize(c_name), sanitize(cls_name), sanitize(str(day)))
                                path = save_stream(r, out_dir)
                                rows.append((link,'ok',path))
                            else:
                                rows.append((link,f'skip {r.status_code}|{ctype}',None))
                        except Exception as e:
                            rows.append((link,f'err {e}',None))
                        prog.progress(int(i/len(final)*100))

                    st.dataframe([{'link':l,'status':s,'path':p} for l,s,p in rows])
                    st.success(f'Downloaded {len([r for r in rows if r[1]=="ok"])} files into {DOWNLOAD_DIR}')


# Main flow for single-page downloads (triggered by top-level button)
if download and not contest_mode:
    if not url or 'soaringspot.com' not in url:
        st.error('Enter a valid SoaringSpot URL')
        st.stop()

    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0'})
    try:
        resp = sess.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        st.error(f'Fetch failed: {e}')
        st.stop()

    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    cand = find_candidates(resp.text, base)

    # Non-contest single-page download
    if not cand:
        st.info('No direct .igc or download links found.')
    else:
        st.info(f'Found {len(cand)} candidate link(s).')
        prog = st.progress(0)
        results = []
        for i, link in enumerate(cand, 1):
            fetch = link
            if '/download-contest-flight/' in link and 'dl=' not in link:
                fetch = link + ('&dl=1' if '?' in link else '?dl=1')
            try:
                hdrs = sess.headers.copy(); hdrs.update({'Referer': url, 'Accept': 'application/vnd.flight+igc,application/octet-stream,*/*'})
                r = sess.get(fetch, timeout=30, stream=True, headers=hdrs)
                ctype = r.headers.get('content-type', '').lower()
                if r.status_code == 200 and ('.igc' in ctype or 'flight' in ctype or 'content-disposition' in r.headers or fetch.lower().endswith('.igc')):
                    path = save_stream(r, DOWNLOAD_DIR)
                    results.append((link, 'ok', path))
                else:
                    results.append((link, f'skip {r.status_code}|{ctype}', None))
            except Exception as e:
                results.append((link, f'err {e}', None))
            prog.progress(int(i / len(cand) * 100))

        st.dataframe([{'link': l, 'status': s, 'path': p} for l, s, p in results])
        ok = [r for r in results if r[1] == 'ok']
        st.success(f'Downloaded {len(ok)} files into {DOWNLOAD_DIR}')
