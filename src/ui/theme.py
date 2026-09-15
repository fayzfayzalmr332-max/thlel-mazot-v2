"""Global dark-theme CSS (+RTL) injected once into the Streamlit app."""
from __future__ import annotations

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');

html, body, [class*="css"], .stMarkdown, .stApp {
  font-family: "Cairo", "Segoe UI", Tahoma, Arial, sans-serif;
}
.stApp { background-color: #070d18; color: #e7edf7; }
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }

/* ---------- decorative backdrop ---------- */
.stApp::before {
  content: "";
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(900px 420px at 12% -8%, rgba(34,211,238,.12), transparent 60%),
    radial-gradient(800px 400px at 96% 0%, rgba(245,192,74,.10), transparent 55%),
    radial-gradient(700px 500px at 50% 110%, rgba(239,68,68,.06), transparent 60%);
}

.tm-wrap { direction: rtl; text-align: right; }
.tm-card {
  background: linear-gradient(180deg, #101a2c, #0d1424);
  border: 1px solid #1f2b42;
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 10px;
  box-shadow: 0 4px 18px rgba(0,0,0,.35);
}
.tm-card-title { color: #8b9bb4; font-size: 0.82rem; letter-spacing: .4px; margin-bottom: 2px; }
.tm-card-value { font-size: 1.85rem; font-weight: 900; color: #ffffff; line-height: 1.15; }
.tm-card-unit { color: #8b9bb4; font-size: 0.78rem; }
.tm-up   { color: #22c55e !important; }
.tm-down { color: #ef4444 !important; }
.tm-flat { color: #8b9bb4 !important; }

.tm-chip {
  display: inline-block; background: #16233b; border: 1px solid #24344f;
  color: #a9c0e8; border-radius: 999px; padding: 2px 10px;
  font-size: 0.7rem; margin: 2px 2px 0 0; white-space: nowrap;
}
.tm-badge {
  display:inline-block; border-radius: 6px; padding: 2px 8px;
  font-size: 0.68rem; font-weight: 700; margin-left: 4px;
}
.tm-meta { color: #64748b; font-size: 0.7rem; }

.tm-hero { border-radius: 16px; padding: 20px 24px; color: #06121f; }
.tm-hero .big { font-size: 2.15rem; font-weight: 900; line-height: 1.2; }
.tm-hero .sub { font-size: 0.95rem; font-weight: 700; opacity: .92; }
.tm-hero .more { font-size: 0.78rem; font-weight: 600; opacity: .75; margin-top: 6px; }
.hGREEN  { background: linear-gradient(135deg, #6ee7b7, #22c55e); }
.hYELLOW { background: linear-gradient(135deg, #fde68a, #f5c04a); }
.hRED    { background: linear-gradient(135deg, #fca5a5, #ef4444); }

.tm-sec-h { color: #f5c04a; font-weight: 800; font-size: 1.0rem; margin: 12px 0 6px; }
.tm-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-left: 6px; vertical-align: middle;}

div[data-testid="stTabs"] button { font-family: "Cairo", sans-serif; }
div[data-testid="stDataFrame"] { direction: rtl; }
.stButton button, .stDownloadButton button {
  background:#16233b; border:1px solid #2a3d63; color:#e7edf7; border-radius:10px;
}
.stButton button:hover { border-color:#22d3ee; color:#22d3ee; }

/* Scrollbars */
::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: #0b1220; }
::-webkit-scrollbar-thumb { background: #24344f; border-radius: 6px; }
</style>
"""