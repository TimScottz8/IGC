# Soaring IGC Downloader (Gaggles)

A small Streamlit app to discover and download IGC files from SoaringSpot.

Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Usage

- Paste a SoaringSpot URL into the input box.
- Toggle "Download entire contest (classes & days)" to discover classes.
- Select classes and click "Download selected classes" to download into `igc_downloads/`.

Notes

- Downloads are placed under `igc_downloads/<contest>/<class>/<day>/`.
- Add an API token in the UI to use the SoaringSpot API (optional).
