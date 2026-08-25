import os
import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

DOWNLOAD_DIR = "igc_downloads"
USER_AGENT = "Mozilla/5.0"
DOWNLOAD_ACCEPT = "application/vnd.flight+igc,application/octet-stream,*/*"

# SoaringSpot exposes contest pages and task/result links as ordinary HTML.
# We crawl those links, normalise them, and only keep the direct download endpoints
# that actually point to .igc files or flight payloads.


def sanitize(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"[^A-Za-z0-9 _-]", "_", str(name)).strip()[:150]


def list_downloaded_igc_files(base_dir: str = DOWNLOAD_DIR):
    matches = []
    if not os.path.isdir(base_dir):
        return matches
    for root, _, files in os.walk(base_dir):
        for name in sorted(files):
            if name.lower().endswith('.igc'):
                full_path = os.path.join(root, name)
                matches.append(os.path.relpath(full_path, start='.'))
    return sorted(matches)


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
    # SoaringSpot sometimes serves a page URL that still needs the explicit "dl=1"
    # flag to trigger the actual IGC payload rather than an HTML preview page.
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
        if any(pat in href.lower() for pat in ['/daily', 'task-', '/task/']):
            found_daily.append(href if href.startswith('http') else urljoin(base, href))
    return list(dict.fromkeys(found_daily))


def canonical_url(u):
    p = urlparse(u)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.pop('dl', None)
    query = urlencode(sorted(q.items())) if q else ''
    return urlunparse((p.scheme, p.netloc, p.path, p.params, query, p.fragment))


def dedupe_contest_links(all_links):
    seen = set()
    final = []
    for link, c_name, cls_name, day in all_links:
        key = (canonical_url(link), str(day))
        if key in seen:
            continue
        seen.add(key)
        final.append((link, c_name, cls_name, day))
    return final


def infer_class_pages_from_task_links(html_text: str, base: str):
    s = BeautifulSoup(html_text, "html.parser")
    out = []
    seen = set()
    for a in s.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        abs_url = href if href.startswith('http') else urljoin(base, href)
        p = urlparse(abs_url)
        parts = [seg for seg in p.path.split('/') if seg]
        if 'tasks' not in parts:
            continue
        idx = parts.index('tasks')
        if idx + 1 >= len(parts):
            continue
        class_slug = parts[idx + 1]
        prefix = parts[:idx]
        class_path = '/' + '/'.join(prefix + ['results', class_slug])
        class_url = urlunparse((p.scheme, p.netloc, class_path, '', '', ''))
        class_name = sanitize(class_slug.replace('-', ' ').title())
        if class_url in seen:
            continue
        seen.add(class_url)
        out.append((class_name, class_url))
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
        if iid and ('date' in iid.lower() or 'day' in iid.lower()):
            d = parse_day_from_text(el.get_text() or '')
            if d:
                return d
    p = urlparse(url)
    seg = p.path.rstrip('/').split('/')[-1]
    d = parse_day_from_text(seg)
    if d:
        return d
    return 'day'


def find_class_pages_from_contest(html, base):
    # Contest pages usually list class links to daily task pages. This is the
    # SoaringSpot HTML pattern we follow to discover each class without hard-coding
    # any site-specific URLs.
    s = BeautifulSoup(html, "html.parser")
    classes = []
    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text() or "").strip()
        if not href:
            continue
        url_abs = href if href.startswith('http') else urljoin(base, href)
        path_parts = [seg for seg in urlparse(url_abs).path.split('/') if seg]

        cls_slug = None
        for marker in ('results', 'classes', 'class'):
            if marker in path_parts:
                idx = path_parts.index(marker)
                tail = path_parts[idx + 1:]
                if len(tail) == 1:
                    cls_slug = tail[0]
                break

        if cls_slug:
            cls_name = sanitize(text or cls_slug.replace('-', ' ').title())
            classes.append((cls_name, url_abs))
    seen = set()
    out = []
    for n, u in classes:
        if u in seen:
            continue
        seen.add(u)
        out.append((n, u))
    return out


def discover_class_pages(contest_html: str, contest_url: str, base: str, sess):
    class_pages = find_class_pages_from_contest(contest_html, base)
    if class_pages:
        return class_pages

    results_candidates = [urljoin(contest_url.rstrip('/') + '/', 'results')]
    s = BeautifulSoup(contest_html, "html.parser")
    for a in s.find_all("a", href=True):
        href = (a.get('href') or '').strip()
        if not href:
            continue
        if re.search(r'/results(?:[/?#]|$)', href.lower()):
            abs_url = href if href.startswith('http') else urljoin(base, href)
            results_candidates.append(abs_url)

    seen_results = set()
    fallback_pages = []
    for r_url in results_candidates:
        if r_url in seen_results:
            continue
        seen_results.add(r_url)
        try:
            rr = sess.get(r_url, timeout=15)
            rr.raise_for_status()
            fallback_pages.extend(find_class_pages_from_contest(rr.text, base))
            if not fallback_pages:
                fallback_pages.extend(infer_class_pages_from_task_links(rr.text, base))
        except Exception:
            continue

    if fallback_pages:
        dedup = []
        seen_urls = set()
        for n, u in fallback_pages:
            if u in seen_urls:
                continue
            seen_urls.add(u)
            dedup.append((n, u))
        return dedup

    return infer_class_pages_from_task_links(contest_html, base)


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

    for tag in s.find_all(True):
        for val in tag.attrs.values():
            txt = " ".join(val) if isinstance(val, (list, tuple)) else str(val)
            add_candidate(txt)
            for m in re.findall(r'href=["\']([^"\']+)["\']', unescape(txt)):
                add_candidate(m)

    for match in re.finditer(r'(?:href|src)=(?:["\'])?([^\s"\'>]+)', unescape(html)):
        add_candidate(match.group(1))

    return sorted(candidates)
