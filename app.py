import os
import re
from urllib.parse import urlparse

import requests
import streamlit as st

from download_helpers import (
    DOWNLOAD_ACCEPT,
    DOWNLOAD_DIR,
    USER_AGENT,
    canonical_url,
    dedupe_contest_links,
    discover_class_pages,
    extract_daily_links_from_class_html,
    extract_day_from_page,
    extract_day_from_url,
    fetch_url_for_download,
    find_candidates,
    find_class_pages_from_contest,
    infer_class_pages_from_task_links,
    is_download_response_ok,
    list_downloaded_igc_files,
    save_stream,
    sanitize,
    status_label,
)
from geo_task import (
    build_sector_points,
    extract_start_sector_from_igc,
    extract_task_points_from_igc,
    extract_task_sectors_from_igc,
    parse_igc_lat_lon,
    project_geometry_table,
    project_point_from_bearing,
)
from map_helpers import render_igc_map

st.set_page_config(page_title="Soaring IGC Downloader", layout="wide")
st.title("Soaring IGC Downloader")
st.markdown("Paste a SoaringSpot page URL. Only explicit .igc and download endpoints will be fetched.")

# Keep compatibility for direct imports into the original app module surface.
__all__ = [
    "DOWNLOAD_DIR",
    "USER_AGENT",
    "DOWNLOAD_ACCEPT",
    "sanitize",
    "list_downloaded_igc_files",
    "parse_igc_lat_lon",
    "extract_task_points_from_igc",
    "extract_start_sector_from_igc",
    "extract_task_sectors_from_igc",
    "project_geometry_table",
    "project_point_from_bearing",
    "build_sector_points",
    "render_igc_map",
    "fetch_url_for_download",
    "is_download_response_ok",
    "status_label",
    "extract_daily_links_from_class_html",
    "dedupe_contest_links",
    "infer_class_pages_from_task_links",
    "discover_class_pages",
    "find_class_pages_from_contest",
    "find_candidates",
    "extract_day_from_url",
    "extract_day_from_page",
    "canonical_url",
    "save_stream",
]


download_tab, viewer_tab = st.tabs(["Download", "Flight viewer"])

with download_tab:
    url = st.text_input("SoaringSpot URL", "https://www.soaringspot.com/en_gb/...")
    contest_mode = st.checkbox("Download entire contest (classes & days)", key="contest_mode")
    download = st.button("Download IGCs")

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

                class_pages = discover_class_pages(resp.text, url, base, sess)
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
                        for name in selected:
                            if name in html_classes:
                                cls_url = html_classes[name]
                                st.write(f"### Fetching class: `{name}`")
                                st.write(f"URL: `{cls_url}`")
                                try:
                                    cr = sess.get(cls_url, timeout=12)
                                    cr.raise_for_status()
                                    found_daily = extract_daily_links_from_class_html(cr.text, base)
                                    st.info(f"Found **{len(found_daily)}** daily page links for {name}")
                                    for dl in found_daily[:3]:
                                        st.write(f"  - {dl[-80:]}")
                                    if len(found_daily) > 3:
                                        st.write(f"  ... and {len(found_daily)-3} more")
                                    if found_daily:
                                        for dl in found_daily:
                                            try:
                                                dr = sess.get(dl, timeout=12)
                                                dr.raise_for_status()
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

                        final = dedupe_contest_links(all_links)
                        by_day = {}
                        for link, c_name, cls_name, day in final:
                            by_day.setdefault(str(day), 0)
                            by_day[str(day)] += 1

                        st.info(f"**Found {len(final)} unique links across {len(by_day)} days:**")
                        for day in sorted(by_day.keys()):
                            st.write(f"  • {day}: {by_day[day]} files")
                        st.write("---")

                        st.info(f"Downloading {len(final)} files across {len(by_day)} unique days...")
                        prog = st.progress(0)
                        rows = []
                        for i, (link, c_name, cls_name, day) in enumerate(final, 1):
                            st.write(f"**{i}/{len(final)}** Day: `{day}` | Link: {link[-50:]}")
                            fetch = fetch_url_for_download(link)
                            try:
                                hdrs = sess.headers.copy(); hdrs.update({'Referer': url, 'Accept': DOWNLOAD_ACCEPT})
                                r = sess.get(fetch, stream=True, timeout=30, headers=hdrs)
                                if is_download_response_ok(r, fetch):
                                    out_dir = os.path.join(DOWNLOAD_DIR, sanitize(c_name), sanitize(cls_name), sanitize(str(day)))
                                    path = save_stream(r, out_dir)
                                    rows.append((link, 'ok', path))
                                    st.success(f"✓ Saved to {out_dir}")
                                else:
                                    rows.append((link, status_label(r), None))
                                    st.warning(f"✗ Skipped: {r.status_code} | {r.headers.get('content-type', '')[:30]}")
                            except Exception as e:
                                rows.append((link, f'err {e}', None))
                                st.error(f"✗ Error: {str(e)[:80]}")
                            prog.progress(int(i / len(final) * 100))

                        st.dataframe([{'link': l, 'status': s, 'path': p} for l, s, p in rows])
                        st.success(f'Downloaded {len([r for r in rows if r[1] == "ok"])} files into {DOWNLOAD_DIR}')

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

with viewer_tab:
    available_igc_files = list_downloaded_igc_files()
    selected_igc_file = st.selectbox(
        'Select a downloaded IGC file',
        options=available_igc_files,
        index=0 if available_igc_files else None,
        disabled=not available_igc_files,
    )
    if selected_igc_file:
        st.caption(f"Selected file: {selected_igc_file}")
        geometry_rows = project_geometry_table(selected_igc_file)
        if geometry_rows:
            st.subheader("Task geometry audit")
            st.dataframe(
                geometry_rows,
                use_container_width=True,
                hide_index=True,
                column_order=[
                    "point",
                    "idx",
                    "first_leg_deg",
                    "inbound_deg",
                    "outbound_deg",
                    "internal_bisector_deg",
                    "external_bisector_deg",
                    "style",
                    "radius_m",
                    "inner_radius_m",
                    "a1_deg",
                    "a2_deg",
                    "a12_deg",
                ],
            )
        if st.button("Open selected file", key="open_selected_igc"):
            render_igc_map(selected_igc_file)
