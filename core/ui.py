from __future__ import annotations

from html import escape
from textwrap import dedent

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def render_app_shell(title: str, subtitle: str, chips: list[tuple[str, str]] | None = None) -> None:
    st.set_page_config(page_title="NHS-FLOW", layout="wide")
    chip_markup = "".join(
        f"<span class='nhs-chip'><span>{escape(label)}</span><strong>{escape(value)}</strong></span>"
        for label, value in (chips or [])
        if value
    )
    st.markdown(
        dedent(
            """
        <style>
        :root {
            --bg: #f4f7f2;
            --bg-deep: #e6efe8;
            --surface: rgba(255, 255, 255, 0.88);
            --surface-strong: rgba(255, 255, 255, 0.96);
            --surface-dark: #123b36;
            --text: #17342f;
            --muted: #5b746f;
            --line: rgba(20, 74, 66, 0.12);
            --teal: #0f7668;
            --teal-deep: #0a4f47;
            --orange: #c96b18;
            --red: #b42318;
            --shadow: 0 18px 40px rgba(12, 54, 48, 0.10);
            --shadow-soft: 0 12px 30px rgba(12, 54, 48, 0.07);
            --radius-lg: 24px;
            --radius-md: 18px;
            --radius-sm: 14px;
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(15, 118, 104, 0.16), transparent 26%),
                radial-gradient(circle at 85% 8%, rgba(201, 107, 24, 0.12), transparent 22%),
                linear-gradient(180deg, var(--bg) 0%, var(--bg-deep) 100%);
            color: var(--text);
        }
        .block-container {
            max-width: 1360px;
            padding-top: 1.25rem;
            padding-bottom: 2rem;
        }
        h1, h2, h3, label, p, div, span, .stCaption {
            color: var(--text);
        }
        .nhs-shell {
            position: relative;
            overflow: hidden;
            padding: 1.35rem 1.45rem;
            border-radius: 30px;
            margin-bottom: 1rem;
            border: 1px solid rgba(255,255,255,0.22);
            background:
                linear-gradient(135deg, rgba(8, 49, 45, 0.97), rgba(15, 118, 104, 0.94) 58%, rgba(201, 107, 24, 0.88));
            box-shadow: 0 28px 60px rgba(10, 53, 46, 0.20);
        }
        .nhs-shell::after {
            content: "";
            position: absolute;
            inset: auto -8% -28% auto;
            width: 300px;
            height: 300px;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(255,255,255,0.18), transparent 68%);
        }
        .nhs-shell h1, .nhs-shell p, .nhs-shell span, .nhs-shell strong {
            color: #f3fff9 !important;
        }
        .nhs-shell p {
            margin: 0.45rem 0 0;
            max-width: 760px;
            line-height: 1.45;
            opacity: 0.92;
        }
        .nhs-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.7rem;
            margin-top: 1rem;
        }
        .nhs-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.55rem 0.8rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.14);
            border: 1px solid rgba(255,255,255,0.18);
            backdrop-filter: blur(10px);
            font-size: 0.88rem;
        }
        .nhs-chip span {
            opacity: 0.78;
        }
        .nhs-card, .table-card {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(10px);
        }
        .table-card {
            padding: 1rem 1rem 0.7rem;
            margin-bottom: 1rem;
        }
        .table-card h3 {
            margin: 0 0 0.2rem;
            font-size: 1rem;
        }
        .table-card p {
            margin: 0 0 0.9rem;
            color: var(--muted);
            font-size: 0.9rem;
        }
        .metric-band {
            padding: 1.05rem;
            border-radius: 26px;
            border: 1px solid var(--line);
            background: linear-gradient(180deg, rgba(255,255,255,0.78), rgba(255,255,255,0.96));
            box-shadow: var(--shadow);
            margin-bottom: 1rem;
        }
        .metric-band-header {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.9rem;
        }
        .metric-band-header h3 {
            margin: 0;
            font-size: 1.05rem;
        }
        .metric-band-header p {
            margin: 0.25rem 0 0;
            color: var(--muted);
            font-size: 0.9rem;
        }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.85rem;
        }
        .metric-item {
            min-width: 0;
            padding: 1rem;
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(10, 79, 71, 0.96), rgba(15, 118, 104, 0.96));
            color: #f4fff9 !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.10);
        }
        .metric-item.warn {
            background: linear-gradient(180deg, rgba(165, 95, 22, 0.96), rgba(201, 107, 24, 0.96));
        }
        .metric-item.danger {
            background: linear-gradient(180deg, rgba(131, 31, 26, 0.96), rgba(180, 35, 24, 0.96));
        }
        .metric-item .label {
            display: block;
            font-size: 0.82rem;
            opacity: 0.82;
            margin-bottom: 0.35rem;
        }
        .metric-item .value {
            display: block;
            font-size: 1.65rem;
            line-height: 1.05;
            font-weight: 800;
            letter-spacing: -0.03em;
        }
        .metric-item .meta {
            display: block;
            margin-top: 0.4rem;
            font-size: 0.82rem;
            opacity: 0.8;
        }
        .alert-card {
            padding: 1rem 1rem;
            border-left: 5px solid var(--orange);
            background: rgba(255, 248, 239, 0.92);
            border-radius: var(--radius-sm);
            margin-bottom: 0.7rem;
            box-shadow: var(--shadow-soft);
        }
        .danger-cell {
            background: #fff1f3 !important;
            color: var(--red) !important;
            font-weight: 700;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.55rem;
            padding: 0.35rem;
            background: rgba(255,255,255,0.55);
            border: 1px solid var(--line);
            border-radius: 18px;
            margin-bottom: 0.75rem;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 0.6rem 1rem;
            border-radius: 14px;
            background: transparent;
        }
        .stTabs [aria-selected="true"] {
            background: rgba(11, 93, 82, 0.14) !important;
        }
        .stButton > button {
            border: 0;
            border-radius: 14px;
            min-height: 3rem;
            font-weight: 700;
            color: #f7fffc !important;
            background: linear-gradient(135deg, var(--teal-deep), var(--teal));
            box-shadow: 0 12px 24px rgba(11, 93, 82, 0.18);
        }
        .stButton > button:hover {
            background: linear-gradient(135deg, #0d675c, #14907e);
            color: #ffffff !important;
        }
        .stTextArea textarea, .stTextInput input, .stNumberInput input {
            border-radius: 14px !important;
            background: rgba(255,255,255,0.92) !important;
        }
        table.nhs-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            background: var(--surface-strong);
            overflow: hidden;
            border-radius: 16px;
        }
        table.nhs-table thead th {
            position: sticky;
            top: 0;
            background: linear-gradient(180deg, #0d5e53, #0a4f47);
            color: #f4fff9 !important;
            text-align: left;
            padding: 0.85rem 0.9rem;
            font-size: 0.9rem;
        }
        table.nhs-table tbody td {
            padding: 0.8rem 0.9rem;
            border-bottom: 1px solid rgba(14, 65, 58, 0.08);
            background: rgba(255,255,255,0.92);
        }
        table.nhs-table tbody tr:nth-child(even) td {
            background: rgba(243, 248, 245, 0.96);
        }
        @media (max-width: 960px) {
            .metric-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .block-container {
                padding-top: 0.75rem;
            }
        }
        @media (max-width: 640px) {
            .metric-grid {
                grid-template-columns: 1fr;
            }
            .nhs-shell {
                padding: 1.1rem;
                border-radius: 24px;
            }
        }
        </style>
        """
        ),
        unsafe_allow_html=True,
    )
    components.html(
        dedent(
            f"""
        <html>
        <head>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: transparent;
                    font-family: "Segoe UI", sans-serif;
                }}
                .nhs-shell {{
                    position: relative;
                    overflow: hidden;
                    padding: 1.35rem 1.45rem;
                    border-radius: 30px;
                    border: 1px solid rgba(255,255,255,0.22);
                    background:
                        linear-gradient(135deg, rgba(8, 49, 45, 0.97), rgba(15, 118, 104, 0.94) 58%, rgba(201, 107, 24, 0.88));
                    box-shadow: 0 28px 60px rgba(10, 53, 46, 0.20);
                }}
                .nhs-shell::after {{
                    content: "";
                    position: absolute;
                    inset: auto -8% -28% auto;
                    width: 300px;
                    height: 300px;
                    border-radius: 999px;
                    background: radial-gradient(circle, rgba(255,255,255,0.18), transparent 68%);
                }}
                .nhs-shell h1, .nhs-shell p, .nhs-shell span, .nhs-shell strong {{
                    color: #f3fff9;
                }}
                .nhs-shell h1 {{
                    margin: 0;
                    font-size: 2rem;
                }}
                .nhs-shell p {{
                    margin: 0.45rem 0 0;
                    max-width: 760px;
                    line-height: 1.45;
                    opacity: 0.92;
                    font-size: 0.98rem;
                }}
                .nhs-chip-row {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.7rem;
                    margin-top: 1rem;
                }}
                .nhs-chip {{
                    display: inline-flex;
                    align-items: center;
                    gap: 0.45rem;
                    padding: 0.55rem 0.8rem;
                    border-radius: 999px;
                    background: rgba(255,255,255,0.14);
                    border: 1px solid rgba(255,255,255,0.18);
                    backdrop-filter: blur(10px);
                    font-size: 0.88rem;
                }}
                .nhs-chip span {{
                    opacity: 0.78;
                }}
            </style>
        </head>
        <body>
        <div class="nhs-shell">
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
            <div class="nhs-chip-row">{chip_markup}</div>
        </div>
        </body>
        </html>
        """
        ),
        height=180,
        scrolling=False,
    )


def render_metric_band(title: str, items: list[dict], subtitle: str | None = None) -> None:
    cards = []
    for item in items:
        tone = escape(item.get("tone", ""))
        label = escape(str(item.get("label", "")))
        value = escape(str(item.get("value", "")))
        meta = escape(str(item.get("meta", ""))) if item.get("meta") else ""
        cards.append(
            dedent(
                f"""
            <div class="metric-item {tone}">
                <span class="label">{label}</span>
                <span class="value">{value}</span>
                <span class="meta">{meta}</span>
            </div>
            """
            )
        )
    subtitle_markup = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    components.html(
        dedent(
            f"""
        <html>
        <head>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: transparent;
                    font-family: "Segoe UI", sans-serif;
                }}
                .metric-band {{
                    padding: 1.05rem;
                    border-radius: 26px;
                    border: 1px solid rgba(20, 74, 66, 0.12);
                    background: linear-gradient(180deg, rgba(255,255,255,0.78), rgba(255,255,255,0.96));
                    box-shadow: 0 18px 40px rgba(12, 54, 48, 0.10);
                }}
                .metric-band-header h3 {{
                    margin: 0;
                    font-size: 1.05rem;
                    color: #17342f;
                }}
                .metric-band-header p {{
                    margin: 0.25rem 0 0.9rem;
                    color: #5b746f;
                    font-size: 0.9rem;
                }}
                .metric-grid {{
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.85rem;
                }}
                .metric-item {{
                    min-width: 0;
                    padding: 1rem;
                    border-radius: 18px;
                    background: linear-gradient(180deg, rgba(10, 79, 71, 0.96), rgba(15, 118, 104, 0.96));
                    color: #f4fff9;
                    box-shadow: inset 0 1px 0 rgba(255,255,255,0.10);
                }}
                .metric-item.warn {{
                    background: linear-gradient(180deg, rgba(165, 95, 22, 0.96), rgba(201, 107, 24, 0.96));
                }}
                .metric-item.danger {{
                    background: linear-gradient(180deg, rgba(131, 31, 26, 0.96), rgba(180, 35, 24, 0.96));
                }}
                .metric-item .label {{
                    display: block;
                    font-size: 0.82rem;
                    opacity: 0.82;
                    margin-bottom: 0.35rem;
                }}
                .metric-item .value {{
                    display: block;
                    font-size: 1.65rem;
                    line-height: 1.05;
                    font-weight: 800;
                    letter-spacing: -0.03em;
                }}
                .metric-item .meta {{
                    display: block;
                    margin-top: 0.4rem;
                    font-size: 0.82rem;
                    opacity: 0.8;
                }}
            </style>
        </head>
        <body>
        <div class="metric-band">
            <div class="metric-band-header">
                <div>
                    <h3>{escape(title)}</h3>
                    {subtitle_markup}
                </div>
            </div>
            <div class="metric-grid">
                {''.join(cards)}
            </div>
        </div>
        </body>
        </html>
        """
        ),
        height=235,
        scrolling=False,
    )


def dataframe_to_html(dataframe: pd.DataFrame, highlight_rules=None) -> str:
    headers = "".join(f"<th>{escape(str(column))}</th>" for column in dataframe.columns)
    rows = []
    for _, row in dataframe.iterrows():
        cells = []
        for column in dataframe.columns:
            css_class = ""
            if highlight_rules:
                for rule in highlight_rules:
                    if rule(row, column):
                        css_class = " class='danger-cell'"
                        break
            cells.append(f"<td{css_class}>{escape(str(row[column]))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table class='nhs-table'><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def render_table_card(title: str, dataframe: pd.DataFrame, highlight_rules=None, caption: str | None = None) -> None:
    if dataframe.empty:
        st.subheader(title)
        st.info(f"No data available for {title.lower()}.")
        return
    st.subheader(title)
    if caption:
        st.caption(caption)

    safe_frame = dataframe.fillna("").copy()
    for column in safe_frame.columns:
        safe_frame[column] = safe_frame[column].map(lambda value: "" if value is None else str(value))

    table_html = dataframe_to_html(safe_frame, highlight_rules=highlight_rules)
    row_count = max(1, len(safe_frame.index))
    height = min(620, 86 + row_count * 44)
    components.html(
        dedent(
            f"""
            <html>
            <head>
                <style>
                    body {{
                        margin: 0;
                        padding: 0;
                        background: transparent;
                        font-family: "Segoe UI", sans-serif;
                        color: #17342f;
                    }}
                    .table-shell {{
                        border: 1px solid rgba(20, 74, 66, 0.12);
                        border-radius: 16px;
                        overflow: auto;
                        background: rgba(255,255,255,0.96);
                        box-shadow: 0 12px 24px rgba(18, 61, 54, 0.08);
                        max-height: {height - 6}px;
                    }}
                    table.nhs-table {{
                        width: 100%;
                        border-collapse: collapse;
                    }}
                    table.nhs-table thead th {{
                        background: linear-gradient(180deg, #0d5e53, #0a4f47);
                        color: #f4fff9;
                        text-align: left;
                        padding: 12px 14px;
                        font-size: 14px;
                        position: sticky;
                        top: 0;
                    }}
                    table.nhs-table tbody td {{
                        padding: 12px 14px;
                        border-bottom: 1px solid rgba(14, 65, 58, 0.08);
                        font-size: 14px;
                    }}
                    table.nhs-table tbody tr:nth-child(even) td {{
                        background: #f3f8f5;
                    }}
                    .danger-cell {{
                        background: #fff1f3 !important;
                        color: #b42318 !important;
                        font-weight: 700;
                    }}
                </style>
            </head>
            <body>
                <div class="table-shell">
                    {table_html}
                </div>
            </body>
            </html>
            """
        ),
        height=height,
        scrolling=True,
    )
