import os
import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
import streamlit as st

DOWNLOAD_DIR = "igc_downloads"
USER_AGENT = "Mozilla/5.0"
DOWNLOAD_ACCEPT = "application/vnd.flight+igc,application/octet-stream,*/*"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

st.set_page_config(page_title="Soaring IGC Downloader", layout="wide")
st.title("Soaring IGC Downloader")
st.markdown("Paste a SoaringSpot page URL. Only explicit .igc and download endpoints will be fetched.")

url = st.text_input("SoaringSpot URL", "https://www.soaringspot.com/en_gb/...")
contest_mode = st.checkbox("Download entire contest (classes & days)")
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


def fetch_url_for_download(link: str) -> str:
    if '/download-contest-flight/' in link and 'dl=' not in link:
        return link + ('&dl=1' if '?' in link else '?dl=1')
    return link


def is_download_response_ok(r, fetch_url: str) -> bool:
    ctype = r.headers.get('content-type', '').lower()
    return r.status_code == 200 and (
        '.igc' in ctype
        or 'flight' in ctype
        or 'content-disposition' in r.headers
        or fetch_url.lower().endswith('.igc')
    )


def status_label(r) -> str:
    ctype = r.headers.get('content-type', '').lower()
    return f"skip {r.status_code}|{ctype}"


def extract_daily_links_from_class_html(html_text: str, base: str):
    cls_soup = BeautifulSoup(html_text, 'html.parser')
    found_daily = []
    for a in cls_soup.find_all('a', href=True):
        href = a['href']
        # Match daily results or task pages: /daily, /task-, task-X-on-YYYY-MM-DD patterns
        if any(pat in href.lower() for pat in ['/daily', 'task-', '/task/']):
            found_daily.append(href if href.startswith('http') else urljoin(base, href))
    return list(dict.fromkeys(found_daily))


def dedupe_contest_links(all_links):
    seen = set()
    final = []
    for link, c_name, cls_name, day in all_links:
        # dedupe by canonical URL and by explicit task date to avoid repeated daily folders
        key = (canonical_url(link), str(day))
        if key in seen:
            continue
        seen.add(key)
        final.append((link, c_name, cls_name, day))
    return final


def find_candidates(html, base):
    s = BeautifulSoup(html, "html.parser")
    candidates = set()

    def add_candidate(raw):
        if not raw:
            return
        decoded = unescape(str(raw)).strip()
        for m in re.findall(r'https?://[^\s\"\']+|/[^\s\"\']+', decoded):
            lower = m.lower()
            if lower.endswith('.igc') or 'download-contest-flight' in lower or 'download-flight' in lower or '/download/' in lower:
                candidates.add(m if m.startswith('http') else urljoin(base, m))

    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        add_candidate(href)

    # scan attributes for embedded href fragments, popover data-content, JSON blobs, etc.
    for tag in s.find_all(True):
        for val in tag.attrs.values():
            txt = " ".join(val) if isinstance(val, (list, tuple)) else str(val)
            add_candidate(txt)
            for m in re.findall(r'href=["\']([^"\']+)["\']', unescape(txt)):
                add_candidate(m)

    # explicit catch for escaped HTML embedded in popover data attributes
    for match in re.finditer(r'(?:href|src)=(?:["\'])?([^\s"\'>]+)', unescape(html)):
        add_candidate(match.group(1))

    return sorted(candidates)


def find_class_pages_from_contest(html, base):
    s = BeautifulSoup(html, "html.parser")
    classes = []
    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text() or "").strip()
        if not href:
            continue
        # Match class result pages but exclude daily task pages
        if any(p in href for p in ("/classes/", "/results/", "/class/")) and not ('/task-' in href and '/daily' in href):
            cls_name = text or href.split('/')[-1]
            url_abs = href if href.startswith('http') else urljoin(base, href)
            classes.append((sanitize(cls_name), url_abs))
    # dedupe by URL, preserving first occurrence
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


def extract_day_from_url(url: str):
    if not url:
        return None
    p = urlparse(url)
    path = p.path.rstrip('/')
    for pat in [
        r"/task[-_]?[^/]*-on-(\d{4}-\d{2}-\d{2})",
        r"/(\d{4}-\d{2}-\d{2})",
    ]:
        m = re.search(pat, path, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def extract_day_from_page(html: str, url: str):
    d = extract_day_from_url(url)
    if d:
        return d
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
        sess.headers.update({'User-Agent': USER_AGENT})
        try:
            resp = sess.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            st.error(f'Fetch failed: {e}')
            resp = None

        if resp:
            base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            st.info('Discovering classes...')
            contest_name = sanitize(urlparse(url).path.split('/')[-2] if '/' in urlparse(url).path else 'contest')
            html_classes = {}
            class_names = []

            # Discover classes from HTML
            class_pages = find_class_pages_from_contest(resp.text, base)
            for n, u in class_pages:
                class_names.append(n)
                html_classes[n] = u

            class_names = sorted(set(class_names))
            if not class_names:
                st.info('No classes found on contest page.')
            else:
                st.write('Discovered classes:')
                st.write(class_names)
                with st.form(key='contest_class_form'):
                    selected = st.multiselect('Select classes to download', options=class_names, default=class_names, key='contest_selected_classes')
                    submitted = st.form_submit_button('Download selected classes')
                if submitted and selected:
                    all_links = []
                    # Download from HTML class pages
                    for name in selected:
                        if name in html_classes:
                            cls_url = html_classes[name]
                            st.write(f"### Fetching class: `{name}`")
                            st.write(f"URL: `{cls_url}`")
                            try:
                                cr = sess.get(cls_url, timeout=12); cr.raise_for_status()
                                found_daily = extract_daily_links_from_class_html(cr.text, base)
                                st.info(f"Found **{len(found_daily)}** daily page links for {name}")
                                for dl in found_daily[:3]:  # Show first 3
                                    st.write(f"  - {dl[-80:]}")
                                if len(found_daily) > 3:
                                    st.write(f"  ... and {len(found_daily)-3} more")
                                if found_daily:
                                    for dl in found_daily:
                                        try:
                                            dr = sess.get(dl, timeout=12); dr.raise_for_status()
                                            day = extract_day_from_url(dl) or extract_day_from_page(dr.text, dl) or sanitize(dl.rstrip('/').split('/')[-1])
                                            for link in find_candidates(dr.text, base):
                                                all_links.append((link, contest_name, name, day))
                                        except Exception:
                                            continue
                                else:
                                    page_day = extract_day_from_url(cls_url) or extract_day_from_page(cr.text, cls_url) or 'all'
                                    for link in find_candidates(cr.text, base):
                                        all_links.append((link, contest_name, name, page_day))
                            except Exception:
                                continue

                    # dedupe and download
                    final = dedupe_contest_links(all_links)

                    # Count unique days
                    by_day = {}
                    for link, c_name, cls_name, day in final:
                        by_day.setdefault(str(day), 0)
                        by_day[str(day)] += 1
                    
                    st.info(f"**Found {len(final)} unique links across {len(by_day)} days:**")
                    for day in sorted(by_day.keys()):
                        st.write(f"  • {day}: {by_day[day]} files")
                    st.write("---")

                    st.info(f"Downloading {len(final)} files across {len(by_day)} unique days...")
                    prog = st.progress(0); rows = []
                    for i, (link, c_name, cls_name, day) in enumerate(final, 1):
                        st.write(f"**{i}/{len(final)}** Day: `{day}` | Link: {link[-50:]}")
                        fetch = fetch_url_for_download(link)
                        try:
                            hdrs = sess.headers.copy(); hdrs.update({'Referer': url, 'Accept': DOWNLOAD_ACCEPT})
                            r = sess.get(fetch, stream=True, timeout=30, headers=hdrs)
                            if is_download_response_ok(r, fetch):
                                out_dir = os.path.join(DOWNLOAD_DIR, sanitize(c_name), sanitize(cls_name), sanitize(str(day)))
                                path = save_stream(r, out_dir)
                                rows.append((link,'ok',path))
                                st.success(f"✓ Saved to {out_dir}")
                            else:
                                rows.append((link, status_label(r), None))
                                st.warning(f"✗ Skipped: {r.status_code} | {r.headers.get('content-type', '')[:30]}")
                        except Exception as e:
                            rows.append((link,f'err {e}',None))
                            st.error(f"✗ Error: {str(e)[:80]}")
                        prog.progress(int(i/len(final)*100))

                    st.dataframe([{'link':l,'status':s,'path':p} for l,s,p in rows])
                    st.success(f'Downloaded {len([r for r in rows if r[1]=="ok"])} files into {DOWNLOAD_DIR}')


# Main flow for single-page downloads (triggered by top-level button)
if download and not contest_mode:
    if not url or 'soaringspot.com' not in url:
        st.error('Enter a valid SoaringSpot URL')
        st.stop()

    sess = requests.Session()
    sess.headers.update({'User-Agent': USER_AGENT})
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
            fetch = fetch_url_for_download(link)
            try:
                hdrs = sess.headers.copy(); hdrs.update({'Referer': url, 'Accept': DOWNLOAD_ACCEPT})
                r = sess.get(fetch, timeout=30, stream=True, headers=hdrs)
                if is_download_response_ok(r, fetch):
                    path = save_stream(r, DOWNLOAD_DIR)
                    results.append((link, 'ok', path))
                else:
                    results.append((link, status_label(r), None))
            except Exception as e:
                results.append((link, f'err {e}', None))
            prog.progress(int(i / len(cand) * 100))

        st.dataframe([{'link': l, 'status': s, 'path': p} for l, s, p in results])
        ok = [r for r in results if r[1] == 'ok']
        st.success(f'Downloaded {len(ok)} files into {DOWNLOAD_DIR}')
