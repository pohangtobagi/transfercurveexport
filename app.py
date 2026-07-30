
import io
import re
import uuid
import pickle
from pathlib import Path
from datetime import datetime
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="FET-Analysis_Minjae", layout="wide")
st.title("FET-Analysis_Minjae")

st.markdown("""
<style>
div[data-testid="stSlider"] div[role="slider"] {
    background-color: black !important;
    border-color: black !important;
}
div[data-testid="stSlider"] div[data-testid="stSliderTrack"] > div:nth-child(1) {
    background-color: black !important;
}
div[data-testid="stSlider"] div[role="slider"] > div {
    color: var(--text-color) !important;
    background-color: transparent !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
/* Project radio labels */
section[data-testid="stSidebar"] div[role="radiogroup"] label p {
    font-size: 17px !important;
    font-weight: 700 !important;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label {
    padding-top: 0.35rem !important;
    padding-bottom: 0.35rem !important;
}

/* Right-side device information panel */
.device-panel {
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-radius: 12px;
    padding: 14px 16px 8px 16px;
    margin-bottom: 12px;
    background: rgba(128, 128, 128, 0.06);
}
.device-panel-title {
    font-size: 21px;
    font-weight: 750;
    margin-bottom: 2px;
}
.device-panel-caption {
    font-size: 13px;
    color: #777;
    margin-bottom: 8px;
}

/* Compact right control panel */
div[data-testid="stVerticalBlockBorderWrapper"] {
    padding: 0.45rem 0.55rem 0.55rem 0.55rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] h2 {
    font-size: 15px !important;
    line-height: 1.1 !important;
    margin: 0.1rem 0 0.15rem 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] h3 {
    font-size: 14px !important;
    line-height: 1.1 !important;
    margin: 0.1rem 0 0.15rem 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] p,
div[data-testid="stVerticalBlockBorderWrapper"] label p {
    font-size: 11px !important;
    line-height: 1.15 !important;
    margin-bottom: 0.08rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stCaptionContainer"] {
    margin-top: -0.15rem !important;
    margin-bottom: -0.15rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stSlider"] {
    margin-top: -0.45rem !important;
    margin-bottom: -0.65rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] {
    margin-top: -0.15rem !important;
    margin-bottom: -0.25rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] hr {
    margin: 0.32rem 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stRadio"] {
    margin-top: -0.2rem !important;
    margin-bottom: -0.25rem !important;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# Session log / folder helpers
# ============================================================
STORAGE_DIR = Path(__file__).resolve().parent / ".fet_storage"
STORAGE_FILE = STORAGE_DIR / "projects.pkl"


def _default_persistent_state():
    return {
        "folders": {},
        "active_folder": None,
        "active_log_id": None,
    }


def load_projects_state():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not STORAGE_FILE.exists():
        return _default_persistent_state()

    try:
        with STORAGE_FILE.open("rb") as handle:
            data = pickle.load(handle)
        if not isinstance(data, dict):
            return _default_persistent_state()
        data.setdefault("folders", {})
        data.setdefault("active_folder", None)
        data.setdefault("active_log_id", None)
        return data
    except Exception:
        return _default_persistent_state()


def save_projects_state():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "folders": st.session_state.get("analysis_log_folders", {}),
        "active_folder": st.session_state.get("active_log_folder"),
        "active_log_id": st.session_state.get("persistent_active_log_id"),
    }
    temp_file = STORAGE_FILE.with_suffix(".tmp")
    try:
        with temp_file.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_file.replace(STORAGE_FILE)
    except Exception:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass


def initialize_log_state():
    if "analysis_log_folders" not in st.session_state:
        saved = load_projects_state()
        st.session_state["analysis_log_folders"] = saved["folders"]
        st.session_state["active_log_folder"] = saved["active_folder"]
        st.session_state["persistent_active_log_id"] = saved["active_log_id"]

    if "active_log_folder" not in st.session_state:
        st.session_state["active_log_folder"] = None
    if "persistent_active_log_id" not in st.session_state:
        st.session_state["persistent_active_log_id"] = None


def create_log_folder(folder_name):
    name = str(folder_name).strip()
    if not name:
        return False, "폴더 이름을 입력하세요."

    folders = st.session_state["analysis_log_folders"]
    if name in folders:
        return False, "같은 이름의 프로젝트가 이미 있습니다."

    folders[name] = []
    st.session_state["active_log_folder"] = name
    st.session_state["persistent_active_log_id"] = None
    save_projects_state()
    return True, f"'{name}' 프로젝트를 생성했습니다."


def delete_log_entry(folder_name, entry_id):
    folders = st.session_state["analysis_log_folders"]
    if folder_name not in folders:
        return

    folders[folder_name] = [
        item for item in folders[folder_name]
        if item.get("_log_id") != entry_id
    ]

    if st.session_state.get("persistent_active_log_id") == entry_id:
        st.session_state["persistent_active_log_id"] = None
        st.session_state.pop("active_file_bytes", None)
        st.session_state.pop("active_file_name", None)

    save_projects_state()


def clear_log_folder(folder_name):
    folders = st.session_state["analysis_log_folders"]
    if folder_name in folders:
        folders[folder_name] = []
        st.session_state["persistent_active_log_id"] = None
        st.session_state.pop("active_file_bytes", None)
        st.session_state.pop("active_file_name", None)
        save_projects_state()


def clear_all_logs():
    folders = st.session_state["analysis_log_folders"]
    for name in list(folders.keys()):
        folders[name] = []
    st.session_state["persistent_active_log_id"] = None
    st.session_state.pop("active_file_bytes", None)
    st.session_state.pop("active_file_name", None)
    save_projects_state()


def sci(value, digits=2):
    """HTML scientific notation: xx × 10^xx."""
    if not np.isfinite(value) or value == 0:
        return "N/A" if not np.isfinite(value) else "0"
    exp = int(np.floor(np.log10(abs(value))))
    coef = value / (10 ** exp)
    return f"{coef:.{digits}f} × 10<sup>{exp}</sup>"


def sci_plain(value, digits=2):
    """Excel/plain-text scientific notation."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"

    if not np.isfinite(numeric):
        return "N/A"
    if numeric == 0:
        return "0"

    exp = int(np.floor(np.log10(abs(numeric))))
    coef = numeric / (10 ** exp)
    return f"{coef:.{digits}f} × 10^{exp}"




EXPORT_COLUMNS = [
    "File",
    "Drain voltage",
    "Linear or saturation",
    "Gate voltage range",
    "Gate voltage step",
    "On current (A/um)",
    "Off current (A/um)",
    "on-off ratio",
    "Field-effect mobility",
    "threshold voltage (V)",
    "subthreshold swing (mV/dec)",
]


def log_dataframe(folder_name):
    folders = st.session_state["analysis_log_folders"]
    records = folders.get(folder_name, [])
    if not records:
        return pd.DataFrame(columns=EXPORT_COLUMNS)

    rows = []
    for record in records:
        rows.append({
            "File": record.get("File", ""),
            "Drain voltage": record.get("Drain voltage (V)", np.nan),
            "Linear or saturation": record.get("Operating mode", ""),
            "Gate voltage range": record.get("Gate voltage range", ""),
            "Gate voltage step": record.get("Gate voltage step (V)", np.nan),
            "On current (A/um)": sci_plain(
                record.get("ON current / Width (A/μm)", np.nan)
            ),
            "Off current (A/um)": sci_plain(
                record.get("OFF current / Width (A/μm)", np.nan)
            ),
            "on-off ratio": sci_plain(
                record.get("ON/OFF ratio", np.nan)
            ),
            "Field-effect mobility": record.get(
                "Forward mobility (cm²/V·s)", np.nan
            ),
            "threshold voltage (V)": record.get(
                "Forward Vth (V)", np.nan
            ),
            "subthreshold swing (mV/dec)": record.get(
                "Forward SS (mV/dec)", np.nan
            ),
        })

    return pd.DataFrame(rows, columns=EXPORT_COLUMNS)


def autosize_worksheet(ws):
    """Adjust each column width based on cell content."""
    for column_cells in ws.columns:
        max_length = 0
        column_letter = get_column_letter(column_cells[0].column)

        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            # multiline content: use longest line
            length = max((len(line) for line in value.splitlines()), default=0)
            max_length = max(max_length, length)

        ws.column_dimensions[column_letter].width = min(max(max_length + 3, 12), 45)


def style_parameter_sheet(ws):
    """Light-green header row with readable alignment."""
    header_fill = PatternFill(fill_type="solid", fgColor="C6EFCE")
    header_font = Font(bold=True, color="006100")

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    autosize_worksheet(ws)


def folder_excel_bytes(folder_name):
    df = log_dataframe(folder_name)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Parameters", index=False)
        ws = writer.book["Parameters"]
        style_parameter_sheet(ws)

    output.seek(0)
    return output.getvalue()


def safe_excel_filename(name):
    safe = re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip()
    return safe or "FET_Analysis_Log"


initialize_log_state()


def restore_log_state(record):
    """Restore the uploaded file and every saved analysis selection."""
    file_bytes = record.get("_file_bytes")
    if not file_bytes:
        st.session_state["restore_error"] = "저장된 원본 파일 데이터가 없습니다."
        return

    st.session_state["restored_log_id"] = record.get("_log_id")
    st.session_state["persistent_active_log_id"] = record.get("_log_id")
    st.session_state["active_file_name"] = record.get("File", "restored.xlsx")
    st.session_state["active_file_bytes"] = file_bytes
    st.session_state["restored_file_name"] = record.get("File", "restored.xlsx")
    st.session_state["restored_file_bytes"] = file_bytes
    st.session_state["restored_sheet"] = record.get("Sheet")

    mode = record.get("Operating mode")
    if mode in ["Linear", "Saturation"]:
        st.session_state["operating_mode_widget"] = mode

    if record.get("Width (μm)") is not None:
        st.session_state["width_widget"] = float(record["Width (μm)"])
    if record.get("Length (μm)") is not None:
        st.session_state["length_widget"] = float(record["Length (μm)"])
    if record.get("Cox (nF/cm²)") is not None:
        st.session_state["cox_widget"] = float(record["Cox (nF/cm²)"])

    st.session_state["restored_peak_vg_fwd"] = record.get("Forward peak Vg (V)")
    st.session_state["restored_peak_vg_bwd"] = record.get("Backward peak Vg (V)")
    st.session_state["restored_current_vg_fwd"] = record.get("Selected Forward Vg (V)")
    st.session_state["restored_current_vg_bwd"] = record.get("Selected Backward Vg (V)")
    st.session_state["restored_removed_fwd"] = record.get("_removed_fwd_indices", [])
    st.session_state["restored_removed_bwd"] = record.get("_removed_bwd_indices", [])
    st.session_state["restore_pending"] = True
    save_projects_state()


def auto_restore_last_log():
    """After a browser refresh, automatically reopen the last active saved log."""
    if st.session_state.get("active_file_bytes"):
        return

    active_id = st.session_state.get("persistent_active_log_id")
    if not active_id:
        return

    for records in st.session_state.get("analysis_log_folders", {}).values():
        for record in records:
            if record.get("_log_id") == active_id:
                restore_log_state(record)
                return


def consume_restore_value(key, default=None):
    return st.session_state.pop(key, default)



# ============================================================
# Device information state
# ============================================================
restored_mode = st.session_state.get("restored_operating_mode")
if "operating_mode_widget" not in st.session_state:
    st.session_state["operating_mode_widget"] = (
        restored_mode if restored_mode in ["Linear", "Saturation"] else "Linear"
    )
if "width_widget" not in st.session_state:
    st.session_state["width_widget"] = float(st.session_state.get("restored_W") or 1050.0)
if "length_widget" not in st.session_state:
    st.session_state["length_widget"] = float(st.session_state.get("restored_L") or 100.0)
if "cox_widget" not in st.session_state:
    st.session_state["cox_widget"] = float(st.session_state.get("restored_Cox_nf") or 34.5)

operating_mode = st.session_state["operating_mode_widget"]
W = float(st.session_state["width_widget"])
L = float(st.session_state["length_widget"])
Cox_nf = float(st.session_state["cox_widget"])
Cox = Cox_nf * 1e-9


initialize_log_state()
auto_restore_last_log()

# ============================================================
# Sidebar: Project manager
# ============================================================
initialize_log_state()

st.sidebar.header("Projects")
st.sidebar.caption("프로젝트를 생성하거나 선택한 뒤 분석을 진행하세요.")

project_name_input = st.sidebar.text_input(
    "New project name",
    key="new_project_name_sidebar",
    placeholder="ex) Name",
)

if st.sidebar.button("＋ Create Project", use_container_width=True):
    ok, message = create_log_folder(project_name_input)
    if ok:
        st.sidebar.success(message)
        st.rerun()
    else:
        st.sidebar.warning(message)

project_names = list(st.session_state["analysis_log_folders"].keys())

if project_names:
    project_display_names = [f"📁  {name}" for name in project_names]
    selected_display = st.sidebar.radio(
        "Project list",
        project_display_names,
        index=(
            project_names.index(st.session_state["active_log_folder"])
            if st.session_state.get("active_log_folder") in project_names
            else 0
        ),
        key="project_radio_sidebar",
        label_visibility="collapsed",
    )
    active_project = project_names[project_display_names.index(selected_display)]
    st.session_state["active_log_folder"] = active_project
    save_projects_state()

    active_logs = st.session_state["analysis_log_folders"][active_project]
    st.sidebar.caption(f"Selected: {active_project} · {len(active_logs)} logs")

    if active_logs:
        st.sidebar.download_button(
            "Export Project to Excel",
            data=folder_excel_bytes(active_project),
            file_name=f"{safe_excel_filename(active_project)}_FET_parameters.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"sidebar_export_{active_project}",
        )

        st.sidebar.markdown("**Saved logs**")
        for log_idx, log_record in enumerate(active_logs, start=1):
            log_name_col, log_delete_col = st.sidebar.columns([6, 1])

            if log_name_col.button(
                f"📄 {log_idx}. {log_record.get('File', '')} · {log_record.get('Sheet', '')}",
                key=f"open_log_{active_project}_{log_record['_log_id']}",
                use_container_width=True,
                help="저장 당시 분석 상태로 열기",
            ):
                restore_log_state(log_record)
                st.rerun()

            if log_delete_col.button(
                "✕",
                key=f"sidebar_delete_{active_project}_{log_record['_log_id']}",
                help="이 로그 삭제",
                use_container_width=True,
            ):
                delete_log_entry(active_project, log_record["_log_id"])
                st.rerun()
    else:
        st.sidebar.info("이 프로젝트에는 저장된 로그가 없습니다.")

    project_action_1, project_action_2 = st.sidebar.columns(2)
    if project_action_1.button(
        "Clear Logs",
        key=f"sidebar_clear_{active_project}",
        use_container_width=True,
    ):
        clear_log_folder(active_project)
        st.rerun()

    if project_action_2.button(
        "Delete Project",
        key=f"sidebar_delete_project_{active_project}",
        use_container_width=True,
    ):
        del st.session_state["analysis_log_folders"][active_project]
        st.session_state["active_log_folder"] = None
        st.session_state["persistent_active_log_id"] = None
        st.session_state.pop("active_file_bytes", None)
        st.session_state.pop("active_file_name", None)
        save_projects_state()
        st.rerun()
else:
    active_project = None
    st.session_state["active_log_folder"] = None
    st.sidebar.info("먼저 개인 프로젝트를 생성하세요.")

st.sidebar.markdown("---")

# ============================================================
# Device information state
# ============================================================
restored_mode = st.session_state.get("restored_operating_mode")
if "operating_mode_widget" not in st.session_state:
    st.session_state["operating_mode_widget"] = (
        restored_mode if restored_mode in ["Linear", "Saturation"] else "Linear"
    )
if "width_widget" not in st.session_state:
    st.session_state["width_widget"] = float(st.session_state.get("restored_W") or 1050.0)
if "length_widget" not in st.session_state:
    st.session_state["length_widget"] = float(st.session_state.get("restored_L") or 100.0)
if "cox_widget" not in st.session_state:
    st.session_state["cox_widget"] = float(st.session_state.get("restored_Cox_nf") or 34.5)

operating_mode = st.session_state["operating_mode_widget"]
W = float(st.session_state["width_widget"])
L = float(st.session_state["length_widget"])
Cox_nf = float(st.session_state["cox_widget"])
Cox = Cox_nf * 1e-9

# ============================================================
# Helpers
# ============================================================
def fix_inf(values):
    s = pd.Series(values).replace([np.inf, -np.inf], np.nan)
    return s.ffill().bfill().to_numpy()


def make_card(title, value, color):
    return f"""
    <div style='text-align:left; padding:5px 2px 7px 2px; min-width:0;'>
        <div style='font-size:13px; color:#555; line-height:1.25;
                    min-height:34px; margin-bottom:5px;
                    overflow-wrap:anywhere; word-break:keep-all;'>
            {title}
        </div>
        <div style='font-size:18px; font-weight:700; color:{color};
                    line-height:1.2; min-height:23px;
                    white-space:nowrap; overflow:hidden;
                    text-overflow:ellipsis;'>
            {value}
        </div>
    </div>
    """


def calculate_ss(id_vals, vg_vals):
    """
    기존 앱과 동일한 SS 정의:
    전체 sweep에서 max |d(log10|Id|)/dVg|의 역수.
    """
    id_vals = np.asarray(id_vals, dtype=float)
    vg_vals = np.asarray(vg_vals, dtype=float)

    valid = np.isfinite(id_vals) & np.isfinite(vg_vals)
    if valid.sum() < 3:
        return np.nan

    current = id_vals[valid]
    vg = vg_vals[valid]

    log_id = np.log10(np.abs(current) + 1e-15)
    slope = np.abs(np.gradient(log_id, vg))

    if len(slope) >= 3:
        slope = np.convolve(slope, np.ones(3) / 3.0, mode="same")

    slope = slope[np.isfinite(slope) & (slope > 0)]
    return 1000.0 / np.max(slope) if len(slope) else np.nan



def split_sweep(df):
    work = df.copy().reset_index(drop=True)
    work["__source_index"] = np.arange(len(work), dtype=int)
    work["GateV"] = pd.to_numeric(work["GateV"], errors="coerce")
    work["DrainI"] = pd.to_numeric(work["DrainI"], errors="coerce")
    work = work.dropna(subset=["GateV", "DrainI"]).reset_index(drop=True)

    vg = work["GateV"]
    if abs(vg.max() - vg.iloc[0]) > abs(vg.min() - vg.iloc[0]):
        turning = int(vg.idxmax())
    else:
        turning = int(vg.idxmin())

    fwd = work.iloc[:turning + 1].reset_index(drop=True)
    bwd = work.iloc[turning:].reset_index(drop=True)
    return fwd, bwd


def calc_curves(vg, current, mode, w, l, cox, vd):
    vg = np.asarray(vg, dtype=float)
    current = np.asarray(current, dtype=float)

    if len(vg) < 3:
        nan = np.full(len(vg), np.nan)
        return nan, nan

    if mode == "Linear":
        gm = fix_inf(np.gradient(current, vg))
        mobility = np.abs(gm) * l / (w * cox * abs(vd))
    else:
        sqrt_id = np.sqrt(np.abs(current))
        gm = fix_inf(np.gradient(sqrt_id, vg))
        mobility = (2.0 * l / (w * cox)) * gm**2

    return gm, mobility


def auto_peak_index(mobility):
    values = np.asarray(mobility, dtype=float)
    if len(values) == 0:
        return 0

    finite = np.where(np.isfinite(values), values, -np.inf)

    # 양 끝 미분 artifact를 피하기 위해 가능한 경우 양 끝 2개 제외
    if len(finite) > 5:
        return int(np.argmax(finite[2:-2]) + 2)
    return int(np.argmax(finite))


def parameter_values(
    vg_fwd, id_fwd, gm_fwd, mu_fwd, idx_f,
    vg_bwd, id_bwd, gm_bwd, mu_bwd, idx_b,
    mode, width
):
    vg_fwd = pd.Series(vg_fwd).reset_index(drop=True)
    id_fwd = pd.Series(id_fwd).reset_index(drop=True)
    vg_bwd = pd.Series(vg_bwd).reset_index(drop=True)
    id_bwd = pd.Series(id_bwd).reset_index(drop=True)

    def safe_vth(vg, current, gm, idx):
        if len(vg) == 0 or idx >= len(vg):
            return np.nan

        gm_value = gm[idx]
        if not np.isfinite(gm_value) or abs(gm_value) <= np.finfo(float).eps:
            return np.nan

        numerator = (
            np.sqrt(abs(current.iloc[idx]))
            if mode == "Saturation"
            else current.iloc[idx]
        )
        return float(vg.iloc[idx] - numerator / gm_value)

    vth_f = safe_vth(vg_fwd, id_fwd, gm_fwd, idx_f)
    vth_b = safe_vth(vg_bwd, id_bwd, gm_bwd, idx_b)

    full_current = np.concatenate([
        np.asarray(id_fwd, dtype=float),
        np.asarray(id_bwd, dtype=float)[1:],
    ])

    finite_abs = np.abs(full_current[np.isfinite(full_current)])
    positive_abs = finite_abs[finite_abs > 0]

    on_current = float(np.max(finite_abs)) if len(finite_abs) else np.nan
    off_current = float(np.min(positive_abs)) if len(positive_abs) else np.nan

    return {
        "mu_fwd": float(mu_fwd[idx_f]) if len(mu_fwd) else np.nan,
        "mu_bwd": float(mu_bwd[idx_b]) if len(mu_bwd) else np.nan,
        "vth_fwd": vth_f,
        "vth_bwd": vth_b,
        "peak_vg_fwd": float(vg_fwd.iloc[idx_f]) if len(vg_fwd) else np.nan,
        "peak_vg_bwd": float(vg_bwd.iloc[idx_b]) if len(vg_bwd) else np.nan,
        "ss_fwd": calculate_ss(id_fwd, vg_fwd),
        "ss_bwd": calculate_ss(id_bwd, vg_bwd),
        "hysteresis": (
            abs(vth_f - vth_b)
            if np.isfinite(vth_f) and np.isfinite(vth_b)
            else np.nan
        ),
        "onoff": (
            on_current / off_current
            if np.isfinite(off_current) and off_current > 0
            else np.nan
        ),
        "on_density": on_current / width if np.isfinite(on_current) else np.nan,
        "off_density": off_current / width if np.isfinite(off_current) else np.nan,
    }


def current_density_at_vg(active_df, selected_vg, width):
    """선택한 실제 Vg에서 |DrainI|/Width를 반환."""
    idx = int((active_df["GateV"] - float(selected_vg)).abs().idxmin())
    row = active_df.iloc[idx]
    density = abs(float(row["DrainI_active"])) / float(width)
    return idx, row, density


def state_keys(file_id, sheet_name, mode):
    stem = f"{file_id}_{sheet_name}_{mode}"
    return {
        "removed_fwd": f"removed_fwd_{stem}",
        "removed_bwd": f"removed_bwd_{stem}",
        "remove_slider_fwd": f"remove_slider_fwd_{stem}",
        "remove_slider_bwd": f"remove_slider_bwd_{stem}",
        "peak_slider_fwd": f"peak_slider_fwd_{stem}",
        "peak_slider_bwd": f"peak_slider_bwd_{stem}",
        "force_auto_peak_fwd": f"force_auto_peak_fwd_{stem}",
        "force_auto_peak_bwd": f"force_auto_peak_bwd_{stem}",
        "current_slider_fwd": f"current_slider_fwd_{stem}",
        "current_slider_bwd": f"current_slider_bwd_{stem}",
    }


def initialize_removal_state(keys):
    if keys["removed_fwd"] not in st.session_state:
        st.session_state[keys["removed_fwd"]] = []
    if keys["removed_bwd"] not in st.session_state:
        st.session_state[keys["removed_bwd"]] = []
    if keys["force_auto_peak_fwd"] not in st.session_state:
        st.session_state[keys["force_auto_peak_fwd"]] = False
    if keys["force_auto_peak_bwd"] not in st.session_state:
        st.session_state[keys["force_auto_peak_bwd"]] = False


def build_active_sweep(part, removed_source_indices):
    """수동 제거된 원래 행을 제외하고 나머지 raw 데이터를 그대로 사용."""
    removed = set(int(v) for v in removed_source_indices)
    active = part[~part["__source_index"].isin(removed)].copy().reset_index(drop=True)
    active["DrainI_active"] = active["DrainI"].to_numpy()
    return active


def analyze_sheet(df, file_id, sheet_name):
    if W <= 0 or L <= 0 or Cox <= 0:
        raise ValueError("Width, Length, Capacitance는 모두 0보다 커야 합니다.")

    vd_values = pd.to_numeric(df["DrainV"], errors="coerce").dropna()
    if vd_values.empty:
        raise ValueError("DrainV 값이 없습니다.")

    vd = float(vd_values.iloc[0])
    if operating_mode == "Linear" and abs(vd) <= np.finfo(float).eps:
        raise ValueError("Linear mode에서는 DrainV가 0이 아니어야 합니다.")

    fwd_raw, bwd_raw = split_sweep(df)
    keys = state_keys(file_id, sheet_name, operating_mode)
    initialize_removal_state(keys)

    fwd = build_active_sweep(fwd_raw, st.session_state[keys["removed_fwd"]])
    bwd = build_active_sweep(bwd_raw, st.session_state[keys["removed_bwd"]])

    if len(fwd) < 3 or len(bwd) < 3:
        raise ValueError("점 제거 후 각 sweep에 최소 3개의 데이터가 필요합니다.")

    gm_fwd, mu_fwd = calc_curves(
        fwd["GateV"], fwd["DrainI_active"],
        operating_mode, W, L, Cox, vd
    )
    gm_bwd, mu_bwd = calc_curves(
        bwd["GateV"], bwd["DrainI_active"],
        operating_mode, W, L, Cox, vd
    )

    # 현재 active mobility에서 자동 최대점 탐색
    auto_idx_f = auto_peak_index(mu_fwd)
    auto_idx_b = auto_peak_index(mu_bwd)

    # 최초 실행 또는 Remove/Reset 직후에는 현재 mobility의 실제 최대점으로 강제 재설정
    if (
        keys["peak_slider_fwd"] not in st.session_state
        or st.session_state.get(keys["force_auto_peak_fwd"], False)
    ):
        st.session_state[keys["peak_slider_fwd"]] = float(fwd["GateV"].iloc[auto_idx_f])
        st.session_state[keys["force_auto_peak_fwd"]] = False

    if (
        keys["peak_slider_bwd"] not in st.session_state
        or st.session_state.get(keys["force_auto_peak_bwd"], False)
    ):
        st.session_state[keys["peak_slider_bwd"]] = float(bwd["GateV"].iloc[auto_idx_b])
        st.session_state[keys["force_auto_peak_bwd"]] = False

    peak_target_f = float(st.session_state[keys["peak_slider_fwd"]])
    peak_target_b = float(st.session_state[keys["peak_slider_bwd"]])

    idx_f = int((fwd["GateV"] - peak_target_f).abs().idxmin())
    idx_b = int((bwd["GateV"] - peak_target_b).abs().idxmin())

    # 실제 남아 있는 Vg에 snap
    st.session_state[keys["peak_slider_fwd"]] = float(fwd["GateV"].iloc[idx_f])
    st.session_state[keys["peak_slider_bwd"]] = float(bwd["GateV"].iloc[idx_b])

    params = parameter_values(
        fwd["GateV"], fwd["DrainI_active"], gm_fwd, mu_fwd, idx_f,
        bwd["GateV"], bwd["DrainI_active"], gm_bwd, mu_bwd, idx_b,
        operating_mode, W,
    )

    return {
        "vd": vd,
        "keys": keys,
        "fwd_raw": fwd_raw,
        "bwd_raw": bwd_raw,
        "fwd": fwd,
        "bwd": bwd,
        "gm_fwd": gm_fwd,
        "gm_bwd": gm_bwd,
        "mu_fwd": mu_fwd,
        "mu_bwd": mu_bwd,
        "idx_f": idx_f,
        "idx_b": idx_b,
        "auto_idx_f": auto_idx_f,
        "auto_idx_b": auto_idx_b,
        "params": params,
    }


def nearest_row_by_vg(active_df, selected_vg):
    idx = int((active_df["GateV"] - float(selected_vg)).abs().idxmin())
    return idx, active_df.iloc[idx]




def sorted_unique_vg(active_df):
    """현재 sweep에 남아 있는 실제 Vg 값 목록."""
    values = pd.to_numeric(active_df["GateV"], errors="coerce").dropna().unique()
    return np.sort(values.astype(float))


def initialize_slider_in_range(key, active_df, default_value):
    """위젯이 생성되기 전에만 session_state를 초기화한다."""
    values = sorted_unique_vg(active_df)
    if len(values) == 0:
        return

    if key not in st.session_state:
        nearest = int(np.argmin(np.abs(values - float(default_value))))
        st.session_state[key] = float(values[nearest])
        return

    current = float(st.session_state[key])
    nearest = int(np.argmin(np.abs(values - current)))
    nearest_value = float(values[nearest])

    # 현재 값이 삭제된 Vg라면 위젯 생성 전에 가장 가까운 남은 Vg로 보정
    if not np.isclose(current, nearest_value):
        st.session_state[key] = nearest_value


def step_discrete_slider(state_key, active_df, direction):
    """
    버튼 callback 전용.
    Streamlit widget 생성 이후 직접 값을 바꾸지 않고,
    callback 내부에서 실제 Vg 한 단계씩 이동한다.
    """
    values = sorted_unique_vg(active_df)
    if len(values) == 0:
        return

    current = float(st.session_state.get(state_key, values[0]))
    nearest = int(np.argmin(np.abs(values - current)))
    target = int(np.clip(nearest + int(direction), 0, len(values) - 1))
    st.session_state[state_key] = float(values[target])


def render_discrete_vg_control(
    title,
    slider_label,
    state_key,
    active_df,
    default_value,
    button_prefix,
    parent=None,
):
    """
    − 버튼 | 실제 측정 Vg select_slider | + 버튼

    select_slider options를 실제 남아 있는 Vg 값으로 제한하므로
    슬라이더가 측정 데이터 간격과 정확히 일치한다.
    """
    initialize_slider_in_range(state_key, active_df, default_value)

    values = sorted_unique_vg(active_df)
    if len(values) == 0:
        return np.nan

    options = [float(v) for v in values]

    ui = parent if parent is not None else st.sidebar
    ui.markdown(f"**{title}**")
    minus_col, slider_col, plus_col = ui.columns([1, 5, 1])

    minus_col.button(
        "−",
        key=f"{button_prefix}_minus",
        use_container_width=True,
        on_click=step_discrete_slider,
        args=(state_key, active_df, -1),
    )

    slider_col.select_slider(
        slider_label,
        options=options,
        key=state_key,
        label_visibility="collapsed",
        format_func=lambda value: f"{value:.2f}",
    )

    plus_col.button(
        "+",
        key=f"{button_prefix}_plus",
        use_container_width=True,
        on_click=step_discrete_slider,
        args=(state_key, active_df, +1),
    )

    return float(st.session_state[state_key])




# ============================================================
# Upload
# ============================================================

main_col, device_col = st.columns([4.4, 1.6], gap="large")

if st.session_state.get("restore_error"):
    st.error(st.session_state.pop("restore_error"))

with main_col:
    uploaded_file = st.file_uploader(
        "측정된 엑셀 파일을 업로드하세요",
        type=["xlsx", "xls"],
    )
    main_content = st.container()

with device_col:
    st.markdown(
        """
        <div class="device-panel">
            <div class="device-panel-title">Device Information</div>
            <div class="device-panel-caption">현재 분석에 적용되는 소자 조건</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    operating_mode = st.radio(
        "Operating Mode",
        ["Linear", "Saturation"],
        key="operating_mode_widget",
        horizontal=True,
    )
    W = st.number_input(
        "Width (μm)",
        min_value=0.000001,
        step=50.0,
        key="width_widget",
    )
    L = st.number_input(
        "Length (μm)",
        min_value=0.000001,
        step=50.0,
        key="length_widget",
    )
    Cox_nf = st.number_input(
        "Capacitance (nF/cm⁻²)",
        min_value=0.000001,
        key="cox_widget",
    )
    Cox = Cox_nf * 1e-9

    st.markdown(
        "<div style='font-size:14px; font-weight:700; margin:8px 0 4px 0;'>"
        "Analysis Controls</div>",
        unsafe_allow_html=True,
    )
    # Compact control panel; no internal scrollbar.
    right_controls = st.container(border=True)

# Keep the current file active after a log is clicked and across normal reruns.
if uploaded_file is not None:
    try:
        uploaded_file.seek(0)
        current_file_bytes = uploaded_file.read()
        uploaded_file.seek(0)
        st.session_state["active_file_bytes"] = current_file_bytes
        st.session_state["active_file_name"] = getattr(
            uploaded_file, "name", "uploaded.xlsx"
        )
    except Exception:
        pass
elif st.session_state.get("active_file_bytes"):
    restored_buffer = io.BytesIO(st.session_state["active_file_bytes"])
    restored_buffer.name = st.session_state.get(
        "active_file_name", "restored.xlsx"
    )
    uploaded_file = restored_buffer

with main_content:
    if uploaded_file:
        file_name = getattr(uploaded_file, "name", "uploaded.xlsx")
        file_size = getattr(uploaded_file, "size", None)
        if file_size is None:
            try:
                current_pos = uploaded_file.tell()
                uploaded_file.seek(0, 2)
                file_size = uploaded_file.tell()
                uploaded_file.seek(current_pos)
            except Exception:
                try:
                    file_size = len(uploaded_file.getvalue())
                except Exception:
                    file_size = 0
        file_id = f"{file_name}_{file_size}"
        xls = pd.ExcelFile(uploaded_file)
        target_sheets = [
            s for s in xls.sheet_names
            if s == "Data" or s.lower().startswith("append")
        ]

        if not target_sheets:
            st.error("분석할 수 있는 시트('Data' 또는 'Append...')가 없습니다.")
            st.stop()

        st.sidebar.markdown("---")
        # Select Data Sheet UI removed.
        # Use restored sheet when valid; otherwise prefer "Data", then first valid sheet.
        restored_sheet = st.session_state.get("restored_sheet")
        if restored_sheet in target_sheets:
            selected_sheet = restored_sheet
        elif "Data" in target_sheets:
            selected_sheet = "Data"
        else:
            selected_sheet = target_sheets[0]

        # ========================================================
        # Average mode
        # ========================================================
        if False:
            rows = []

            for sheet in target_sheets:
                df_sheet = pd.read_excel(uploaded_file, sheet_name=sheet)
                if {"GateV", "DrainI", "DrainV"}.issubset(df_sheet.columns):
                    try:
                        result = analyze_sheet(df_sheet, file_id, sheet)
                        rows.append({"Sheet": sheet, **result["params"]})
                    except Exception:
                        pass

            if not rows:
                st.error("유효한 시트가 없습니다.")
                st.stop()

            stats = pd.DataFrame(rows)
            st.markdown(f"### 📊 Statistics ({operating_mode})")

            p = {
                key: stats[key].mean()
                for key in [
                    "mu_fwd", "mu_bwd", "vth_fwd", "vth_bwd",
                    "ss_fwd", "ss_bwd", "hysteresis",
                    "onoff", "on_density", "off_density",
                ]
            }

            st.markdown("<h4 style='color:#6FADCF;'>Forward Sweep Parameters</h4>", unsafe_allow_html=True)
            f1, f2, f3 = st.columns(3)
            f1.markdown(make_card("Peak Mobility", f"{p['mu_fwd']:.2f} cm²/V·s", "#2E60AB"), unsafe_allow_html=True)
            f2.markdown(make_card("Threshold Voltage", f"{p['vth_fwd']:.2f} V", "#A23B72"), unsafe_allow_html=True)
            f3.markdown(make_card("SS", f"{p['ss_fwd']:.1f} mV/dec", "#18A558"), unsafe_allow_html=True)

            st.markdown("<h4 style='color:#F05650;'>Backward Sweep Parameters</h4>", unsafe_allow_html=True)
            b1, b2, b3 = st.columns(3)
            b1.markdown(make_card("Peak Mobility", f"{p['mu_bwd']:.2f} cm²/V·s", "#2E60AB"), unsafe_allow_html=True)
            b2.markdown(make_card("Threshold Voltage", f"{p['vth_bwd']:.2f} V", "#A23B72"), unsafe_allow_html=True)
            b3.markdown(make_card("SS", f"{p['ss_bwd']:.1f} mV/dec", "#18A558"), unsafe_allow_html=True)

            st.markdown("<h4>Overall Device Parameters</h4>", unsafe_allow_html=True)
            o1, o2, o3, o4 = st.columns(4)
            o1.markdown(make_card("On/Off Ratio", sci(p["onoff"]), "#5B5F97"), unsafe_allow_html=True)
            o2.markdown(make_card("ON Current / Width", f"{sci(p['on_density'])} A/μm", "#5B5F97"), unsafe_allow_html=True)
            o3.markdown(make_card("OFF Current / Width", f"{sci(p['off_density'])} A/μm", "#5B5F97"), unsafe_allow_html=True)
            o4.markdown(make_card("Hysteresis", f"{p['hysteresis']:.2f} V", "#5B5F97"), unsafe_allow_html=True)

        # ========================================================
        # Single-sheet mode
        # ========================================================
        else:
            df = pd.read_excel(uploaded_file, sheet_name=selected_sheet)
            required = {"GateV", "DrainI", "DrainV"}

            if not required.issubset(df.columns):
                st.error("GateV, DrainI, DrainV 컬럼이 필요합니다.")
                st.stop()

            try:
                res = analyze_sheet(df, file_id, selected_sheet)
            except Exception as exc:
                st.error(str(exc))
                st.stop()

            keys = res["keys"]
            fwd = res["fwd"]
            bwd = res["bwd"]

            # Apply saved log state once, then rerun with restored selections.
            if st.session_state.get("restore_pending"):
                st.session_state[keys["removed_fwd"]] = list(
                    st.session_state.get("restored_removed_fwd", [])
                )
                st.session_state[keys["removed_bwd"]] = list(
                    st.session_state.get("restored_removed_bwd", [])
                )

                if st.session_state.get("restored_peak_vg_fwd") is not None:
                    st.session_state[keys["peak_slider_fwd"]] = float(
                        st.session_state["restored_peak_vg_fwd"]
                    )
                if st.session_state.get("restored_peak_vg_bwd") is not None:
                    st.session_state[keys["peak_slider_bwd"]] = float(
                        st.session_state["restored_peak_vg_bwd"]
                    )
                if st.session_state.get("restored_current_vg_fwd") is not None:
                    st.session_state[keys["current_slider_fwd"]] = float(
                        st.session_state["restored_current_vg_fwd"]
                    )
                if st.session_state.get("restored_current_vg_bwd") is not None:
                    st.session_state[keys["current_slider_bwd"]] = float(
                        st.session_state["restored_current_vg_bwd"]
                    )

                st.session_state["restore_pending"] = False
                st.rerun()

            # ====================================================
            # ====================================================
            # Compact direction-selective analysis controls
            # ====================================================
            direction_key = f"control_direction_{file_id}_{selected_sheet}_{operating_mode}"
            if direction_key not in st.session_state:
                st.session_state[direction_key] = "Forward"

            control_direction = right_controls.radio(
                "Sweep direction",
                ["Forward", "Reverse"],
                key=direction_key,
                horizontal=True,
                label_visibility="collapsed",
            )
            is_forward_control = control_direction == "Forward"

            # Initialize all states so the hidden direction retains its values.
            initialize_slider_in_range(
                keys["peak_slider_fwd"],
                fwd,
                float(fwd["GateV"].iloc[res["auto_idx_f"]]),
            )
            initialize_slider_in_range(
                keys["peak_slider_bwd"],
                bwd,
                float(bwd["GateV"].iloc[res["auto_idx_b"]]),
            )
            initialize_slider_in_range(
                keys["remove_slider_fwd"],
                fwd,
                float(fwd["GateV"].iloc[res["auto_idx_f"]]),
            )
            initialize_slider_in_range(
                keys["remove_slider_bwd"],
                bwd,
                float(bwd["GateV"].iloc[res["auto_idx_b"]]),
            )
            initialize_slider_in_range(
                keys["current_slider_fwd"],
                fwd,
                float(fwd["GateV"].iloc[0]),
            )
            initialize_slider_in_range(
                keys["current_slider_bwd"],
                bwd,
                float(bwd["GateV"].iloc[0]),
            )

            # ====================================================
            # Mobility peak point
            # ====================================================
            right_controls.markdown("### Mobility Peak Point")
            active_peak_df = fwd if is_forward_control else bwd
            active_peak_key = (
                keys["peak_slider_fwd"] if is_forward_control
                else keys["peak_slider_bwd"]
            )
            active_auto_idx = res["auto_idx_f"] if is_forward_control else res["auto_idx_b"]
            direction_short = "Fwd" if is_forward_control else "Rev"

            active_peak_vg = render_discrete_vg_control(
                title=f"{control_direction} peak Vg",
                slider_label=f"{control_direction} peak Vg",
                state_key=active_peak_key,
                active_df=active_peak_df,
                default_value=float(active_peak_df["GateV"].iloc[active_auto_idx]),
                button_prefix=(
                    f"peak_{direction_short}_{file_id}_{selected_sheet}_{operating_mode}"
                ),
                parent=right_controls,
            )

            peak_f_vg = float(st.session_state[keys["peak_slider_fwd"]])
            peak_b_vg = float(st.session_state[keys["peak_slider_bwd"]])
            idx_f = int((fwd["GateV"] - peak_f_vg).abs().idxmin())
            idx_b = int((bwd["GateV"] - peak_b_vg).abs().idxmin())

            params = parameter_values(
                fwd["GateV"], fwd["DrainI_active"],
                res["gm_fwd"], res["mu_fwd"], idx_f,
                bwd["GateV"], bwd["DrainI_active"],
                res["gm_bwd"], res["mu_bwd"], idx_b,
                operating_mode, W,
            )

            active_mu = params["mu_fwd"] if is_forward_control else params["mu_bwd"]
            right_controls.caption(
                f"Vg {active_peak_vg:.2f} V · μ {active_mu:.3g} cm²/V·s"
            )

            if right_controls.button(
                f"Auto Max {direction_short}",
                key=f"auto_max_{direction_short}_{file_id}_{selected_sheet}_{operating_mode}",
                use_container_width=True,
            ):
                force_key = (
                    keys["force_auto_peak_fwd"] if is_forward_control
                    else keys["force_auto_peak_bwd"]
                )
                st.session_state[force_key] = True
                st.rerun()

            # ====================================================
            # Manual mobility point removal
            # ====================================================
            right_controls.markdown("---")
            right_controls.markdown("### Manual Point Removal")

            active_remove_df = fwd if is_forward_control else bwd
            active_remove_key = (
                keys["remove_slider_fwd"] if is_forward_control
                else keys["remove_slider_bwd"]
            )
            active_remove_vg = render_discrete_vg_control(
                title=f"{control_direction} removal Vg",
                slider_label=f"{control_direction} removal Vg",
                state_key=active_remove_key,
                active_df=active_remove_df,
                default_value=float(active_remove_df["GateV"].iloc[active_auto_idx]),
                button_prefix=(
                    f"remove_{direction_short}_{file_id}_{selected_sheet}_{operating_mode}"
                ),
                parent=right_controls,
            )

            active_remove_idx, active_remove_row = nearest_row_by_vg(
                active_remove_df, active_remove_vg
            )
            active_mu_array = res["mu_fwd"] if is_forward_control else res["mu_bwd"]
            active_remove_mu = float(active_mu_array[active_remove_idx])
            right_controls.caption(
                f"Vg {active_remove_row['GateV']:.2f} V · "
                f"μ {active_remove_mu:.3g} cm²/V·s"
            )

            remove_col, reset_col = right_controls.columns(2)
            if remove_col.button(
                f"Remove {direction_short}",
                key=f"remove_btn_{direction_short}_{file_id}_{selected_sheet}_{operating_mode}",
                use_container_width=True,
            ):
                source_idx = int(active_remove_row["__source_index"])
                removed_key = (
                    keys["removed_fwd"] if is_forward_control
                    else keys["removed_bwd"]
                )
                force_key = (
                    keys["force_auto_peak_fwd"] if is_forward_control
                    else keys["force_auto_peak_bwd"]
                )
                removed = list(st.session_state[removed_key])
                if source_idx not in removed:
                    removed.append(source_idx)
                    st.session_state[removed_key] = removed
                st.session_state[force_key] = True
                st.rerun()

            if reset_col.button(
                f"Reset {direction_short}",
                key=f"reset_btn_{direction_short}_{file_id}_{selected_sheet}_{operating_mode}",
                use_container_width=True,
            ):
                removed_key = (
                    keys["removed_fwd"] if is_forward_control
                    else keys["removed_bwd"]
                )
                force_key = (
                    keys["force_auto_peak_fwd"] if is_forward_control
                    else keys["force_auto_peak_bwd"]
                )
                st.session_state[removed_key] = []
                st.session_state[force_key] = True
                st.rerun()

            # Compute both direction removal targets for plotting/saved state.
            selected_f_vg = float(st.session_state[keys["remove_slider_fwd"]])
            selected_b_vg = float(st.session_state[keys["remove_slider_bwd"]])
            selected_f_idx, selected_f_row = nearest_row_by_vg(fwd, selected_f_vg)
            selected_b_idx, selected_b_row = nearest_row_by_vg(bwd, selected_b_vg)
            selected_f_mu = float(res["mu_fwd"][selected_f_idx])
            selected_b_mu = float(res["mu_bwd"][selected_b_idx])

            removed_f_count = len(st.session_state[keys["removed_fwd"]])
            removed_b_count = len(st.session_state[keys["removed_bwd"]])
            right_controls.caption(
                f"Removed · Fwd {removed_f_count} / Rev {removed_b_count}"
            )

            # ====================================================
            # Transfer current point
            # ====================================================
            right_controls.markdown("---")
            right_controls.markdown("### Transfer Current Point")

            active_current_df = fwd if is_forward_control else bwd
            active_current_key = (
                keys["current_slider_fwd"] if is_forward_control
                else keys["current_slider_bwd"]
            )
            active_current_vg = render_discrete_vg_control(
                title=f"{control_direction} transfer Vg",
                slider_label=f"{control_direction} transfer Vg",
                state_key=active_current_key,
                active_df=active_current_df,
                default_value=float(active_current_df["GateV"].iloc[0]),
                button_prefix=(
                    f"current_{direction_short}_{file_id}_{selected_sheet}_{operating_mode}"
                ),
                parent=right_controls,
            )

            current_f_vg = float(st.session_state[keys["current_slider_fwd"]])
            current_b_vg = float(st.session_state[keys["current_slider_bwd"]])
            current_f_idx, current_f_row, current_f_density = current_density_at_vg(
                fwd, current_f_vg, W
            )
            current_b_idx, current_b_row, current_b_density = current_density_at_vg(
                bwd, current_b_vg, W
            )

            active_density = (
                current_f_density if is_forward_control else current_b_density
            )
            right_controls.caption(
                f"|Id|/W = {sci_plain(active_density)} A/μm"
            )

            # Central analysis layout: parameters left, plots right
            # ====================================================
            parameter_panel, plot_panel = st.columns([1.05, 1.55], gap="large")

            with parameter_panel:
                parameter_panel.markdown(
                    f"<h3 style='color:#333;'>📊 Data Sheet: {selected_sheet} "
                    f"({operating_mode})</h3>",
                    unsafe_allow_html=True,
                )

                parameter_panel.markdown("<h4 style='color:#6FADCF;'>Forward Sweep Parameters</h4>", unsafe_allow_html=True)
                f1, f2 = parameter_panel.columns(2)
                f1.markdown(make_card("Peak Mobility (cm²/V·s)", f"{params['mu_fwd']:.2f}", "#2E60AB"), unsafe_allow_html=True)
                f2.markdown(make_card("Threshold Voltage, Vₜₕ (V)", f"{params['vth_fwd']:.2f}", "#A23B72"), unsafe_allow_html=True)
                f3, f4 = parameter_panel.columns(2)
                f3.markdown(make_card("Peak Point, Vg (V)", f"{params['peak_vg_fwd']:.1f}", "#F18F01"), unsafe_allow_html=True)
                f4.markdown(make_card("SS (mV/dec)", f"{params['ss_fwd']:.1f}", "#18A558"), unsafe_allow_html=True)

                parameter_panel.markdown("<h4 style='color:#F05650;'>Backward Sweep Parameters</h4>", unsafe_allow_html=True)
                b1, b2 = parameter_panel.columns(2)
                b1.markdown(make_card("Peak Mobility (cm²/V·s)", f"{params['mu_bwd']:.2f}", "#2E60AB"), unsafe_allow_html=True)
                b2.markdown(make_card("Threshold Voltage, Vₜₕ (V)", f"{params['vth_bwd']:.2f}", "#A23B72"), unsafe_allow_html=True)
                b3, b4 = parameter_panel.columns(2)
                b3.markdown(make_card("Peak Point, Vg (V)", f"{params['peak_vg_bwd']:.1f}", "#F18F01"), unsafe_allow_html=True)
                b4.markdown(make_card("SS (mV/dec)", f"{params['ss_bwd']:.1f}", "#18A558"), unsafe_allow_html=True)

                parameter_panel.markdown("<h4>Overall Device Parameters</h4>", unsafe_allow_html=True)
                o1, o2 = parameter_panel.columns(2)
                o1.markdown(make_card("ON/OFF Ratio", sci(params["onoff"]), "#5B5F97"), unsafe_allow_html=True)
                o2.markdown(make_card("ON Current / Width (A/μm)", sci(params['on_density']), "#5B5F97"), unsafe_allow_html=True)
                o3, o4 = parameter_panel.columns(2)
                o3.markdown(make_card("OFF Current / Width (A/μm)", sci(params['off_density']), "#5B5F97"), unsafe_allow_html=True)
                o4.markdown(make_card("Hysteresis (V)", f"{params['hysteresis']:.2f}", "#5B5F97"), unsafe_allow_html=True)

                parameter_panel.markdown("<h4 style='color:#555;'>Selected Transfer Current Density</h4>", unsafe_allow_html=True)
                c1, c2 = parameter_panel.columns(2)
                c1.markdown(make_card("Forward Vg (V)", f"{float(current_f_row['GateV']):.2f}", "#2E60AB"), unsafe_allow_html=True)
                c2.markdown(make_card("Forward |Id| / W (A/μm)", sci(current_f_density), "#2E60AB"), unsafe_allow_html=True)
                c3, c4 = parameter_panel.columns(2)
                c3.markdown(make_card("Backward Vg (V)", f"{float(current_b_row['GateV']):.2f}", "#F05650"), unsafe_allow_html=True)
                c4.markdown(make_card("Backward |Id| / W (A/μm)", sci(current_b_density), "#F05650"), unsafe_allow_html=True)

                # ====================================================
                # Save current result to selected folder
                # ====================================================
                parameter_panel.markdown("<h4>Save Analysis Result</h4>", unsafe_allow_html=True)
                save_col1, save_col2 = parameter_panel.columns([3, 1])

                current_project = st.session_state.get("active_log_folder")
                if current_project:
                    save_col1.info(f"Current project: {current_project}")
                else:
                    save_col1.warning("왼쪽 Projects에서 프로젝트를 먼저 생성하세요.")

                if save_col2.button(
                    "Add to Project",
                    use_container_width=True,
                    disabled=current_project is None,
                ):
                    # Store file bytes and exact analysis selections for click-to-restore.
                    try:
                        uploaded_file.seek(0)
                        saved_file_bytes = uploaded_file.read()
                        uploaded_file.seek(0)
                    except Exception:
                        saved_file_bytes = None

                    log_entry = {
                        "_log_id": str(uuid.uuid4()),
                        "_file_bytes": saved_file_bytes,
                        "_removed_fwd_indices": list(st.session_state[keys["removed_fwd"]]),
                        "_removed_bwd_indices": list(st.session_state[keys["removed_bwd"]]),
                        "Saved at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "File": uploaded_file.name,
                        "Sheet": selected_sheet,
                        "Operating mode": operating_mode,
                        "Width (μm)": float(W),
                        "Length (μm)": float(L),
                        "Cox (nF/cm²)": float(Cox_nf),
                        "Drain voltage (V)": float(res["vd"]),
                        "Gate voltage range": (
                            f"{float(min(fwd['GateV'].min(), bwd['GateV'].min())):.2f} "
                            f"to {float(max(fwd['GateV'].max(), bwd['GateV'].max())):.2f} V"
                        ),
                        "Gate voltage step (V)": float(
                            np.median(np.abs(np.diff(fwd["GateV"])))
                        ) if len(fwd) > 1 else np.nan,
                        "Forward mobility (cm²/V·s)": float(params["mu_fwd"]),
                        "Forward Vth (V)": float(params["vth_fwd"]),
                        "Forward peak Vg (V)": float(params["peak_vg_fwd"]),
                        "Forward SS (mV/dec)": float(params["ss_fwd"]),
                        "Backward mobility (cm²/V·s)": float(params["mu_bwd"]),
                        "Backward Vth (V)": float(params["vth_bwd"]),
                        "Backward peak Vg (V)": float(params["peak_vg_bwd"]),
                        "Backward SS (mV/dec)": float(params["ss_bwd"]),
                        "Hysteresis (V)": float(params["hysteresis"]),
                        "ON/OFF ratio": float(params["onoff"]),
                        "ON current / Width (A/μm)": float(params["on_density"]),
                        "OFF current / Width (A/μm)": float(params["off_density"]),
                        "Selected Forward Vg (V)": float(current_f_row["GateV"]),
                        "Selected Forward |Id| / W (A/μm)": float(current_f_density),
                        "Selected Backward Vg (V)": float(current_b_row["GateV"]),
                        "Selected Backward |Id| / W (A/μm)": float(current_b_density),
                        "Removed Forward points": int(removed_f_count),
                        "Removed Backward points": int(removed_b_count),
                    }
                    st.session_state["analysis_log_folders"][current_project].append(log_entry)
                    st.session_state["active_log_folder"] = current_project
                    st.session_state["persistent_active_log_id"] = log_entry["_log_id"]
                    st.session_state["active_file_bytes"] = saved_file_bytes
                    st.session_state["active_file_name"] = uploaded_file.name
                    save_projects_state()
                    parameter_panel.success(f"'{current_project}' 프로젝트에 로그를 저장했습니다.")
                    st.rerun()


            with plot_panel:

                graph_mobility_title = (
                    "Linear Mobility"
                    if operating_mode == "Linear"
                    else "Saturation Mobility"
                )

                fig = make_subplots(
                    rows=3,
                    cols=1,
                    subplot_titles=(
                        "Transfer (Log Scale)",
                        "Transfer (Linear Scale)",
                        graph_mobility_title,
                    ),
                    vertical_spacing=0.12,
                )

                color_fwd = "blue"
                color_bwd = "red"

                vg_fwd = fwd["GateV"]
                id_fwd = fwd["DrainI_active"]
                vg_bwd = bwd["GateV"]
                id_bwd = bwd["DrainI_active"]

                # Transfer log
                fig.add_trace(go.Scatter(
                    x=vg_fwd, y=np.abs(id_fwd),
                    name="Forward", line=dict(color=color_fwd),
                ), row=1, col=1)
                fig.add_trace(go.Scatter(
                    x=vg_bwd, y=np.abs(id_bwd),
                    name="Backward", line=dict(color=color_bwd),
                ), row=1, col=1)

                if "GateI" in df.columns and removed_f_count == 0 and removed_b_count == 0:
                    ig = pd.to_numeric(df["GateI"], errors="coerce")
                    turning = len(res["fwd_raw"]) - 1
                    ig_f = ig.iloc[:turning + 1].reset_index(drop=True)
                    ig_b = ig.iloc[turning:].reset_index(drop=True)
                    fig.add_trace(go.Scatter(
                        x=res["fwd_raw"]["GateV"], y=np.abs(ig_f),
                        name="Ig (Fwd)", line=dict(color="dimgray", dash="dot"),
                        showlegend=False,
                    ), row=1, col=1)
                    fig.add_trace(go.Scatter(
                        x=res["bwd_raw"]["GateV"], y=np.abs(ig_b),
                        name="Ig (Bwd)", line=dict(color="dimgray", dash="dot"),
                        showlegend=False,
                    ), row=1, col=1)

                # Transfer linear
                fig.add_trace(go.Scatter(
                    x=vg_fwd, y=np.abs(id_fwd),
                    name="Forward", line=dict(color=color_fwd),
                    showlegend=False,
                ), row=2, col=1)
                fig.add_trace(go.Scatter(
                    x=vg_bwd, y=np.abs(id_bwd),
                    name="Backward", line=dict(color=color_bwd),
                    showlegend=False,
                ), row=2, col=1)

                # Selected transfer points
                for row_num in (1, 2):
                    fig.add_trace(go.Scatter(
                        x=[float(current_f_row["GateV"])],
                        y=[abs(float(current_f_row["DrainI_active"]))],
                        mode="markers",
                        marker=dict(
                            symbol="circle-open", size=11, color="black",
                            line=dict(width=2)
                        ),
                        showlegend=False,
                    ), row=row_num, col=1)
                    fig.add_trace(go.Scatter(
                        x=[float(current_b_row["GateV"])],
                        y=[abs(float(current_b_row["DrainI_active"]))],
                        mode="markers",
                        marker=dict(
                            symbol="square-open", size=11, color="black",
                            line=dict(width=2)
                        ),
                        showlegend=False,
                    ), row=row_num, col=1)

                # Mobility only — conductance plot removed
                fig.add_trace(go.Scatter(
                    x=vg_fwd, y=res["mu_fwd"],
                    name="Forward mobility", line=dict(color=color_fwd),
                    showlegend=False,
                ), row=3, col=1)
                fig.add_trace(go.Scatter(
                    x=vg_bwd, y=res["mu_bwd"],
                    name="Backward mobility", line=dict(color=color_bwd),
                    showlegend=False,
                ), row=3, col=1)

                fig.add_trace(go.Scatter(
                    x=[float(selected_f_row["GateV"])],
                    y=[selected_f_mu],
                    mode="markers",
                    marker=dict(symbol="x", size=13, color="black", line=dict(width=2)),
                    showlegend=False,
                ), row=3, col=1)
                fig.add_trace(go.Scatter(
                    x=[float(selected_b_row["GateV"])],
                    y=[selected_b_mu],
                    mode="markers",
                    marker=dict(symbol="x", size=13, color="black", line=dict(width=2)),
                    showlegend=False,
                ), row=3, col=1)

                peak_f_vg = params["peak_vg_fwd"]
                peak_b_vg = params["peak_vg_bwd"]
                fig.add_vline(
                    x=peak_f_vg, line_width=1.5, line_dash="dash",
                    line_color=color_fwd, row=3, col=1
                )
                fig.add_vline(
                    x=peak_b_vg, line_width=1.5, line_dash="dash",
                    line_color=color_bwd, row=3, col=1
                )

                vd_formatted = f"{res['vd']:.2f}".rstrip("0").rstrip(".")
                fig.add_annotation(
                    x=0.01, y=0.02, xref="x domain", yref="y domain",
                    text=f"<b>V<sub>D</sub> = {vd_formatted} V</b>",
                    showarrow=False, font=dict(size=12, color="black"),
                    row=1, col=1,
                )

                common_axis = dict(
                    ticks="outside", tickwidth=1.5, tickcolor="black", ticklen=7,
                    showline=True, linewidth=1.5, linecolor="black", mirror=True,
                    showgrid=True, gridwidth=1, gridcolor="lightgray",
                    griddash="dot", zeroline=False,
                    title_font=dict(size=16), tickfont=dict(size=12),
                )

                vg_all = pd.concat([vg_fwd, vg_bwd])
                vg_range = abs(vg_all.max() - vg_all.min())
                dynamic_dtick = 2.5 if vg_range <= 10 else 10

                fig.update_xaxes(
                    title_text="Gate Voltage (V)", dtick=dynamic_dtick, **common_axis
                )
                fig.update_yaxes(**common_axis)
                fig.update_yaxes(
                    title_text="Drain Current (A)", type="log", row=1, col=1
                )
                fig.update_yaxes(
                    title_text="Drain Current (A)", row=2, col=1
                )
                fig.update_yaxes(
                    title_text=f"{graph_mobility_title} (cm²/V·s)", row=3, col=1
                )

                fig.update_layout(
                    height=980,
                    autosize=True,
                    template="plotly_white",
                    margin=dict(t=80, b=60, l=75, r=25),
                    legend=dict(orientation="h", y=1.04, x=0),
                )
                fig.update_annotations(font_size=16)
                plot_panel.plotly_chart(fig, use_container_width=True)

            # ====================================================
            # Download active data
            # ====================================================
            export_df = pd.concat([
                pd.DataFrame({
                    "GateV_forward": vg_fwd.reset_index(drop=True),
                    "DrainI_forward_active": id_fwd.reset_index(drop=True),
                    "DrainI_over_width_forward_A_per_um": np.abs(id_fwd.reset_index(drop=True)) / W,
                    "gm_forward_active": pd.Series(res["gm_fwd"]),
                    "mobility_forward_active": pd.Series(res["mu_fwd"]),
                    "source_index_forward": fwd["__source_index"].reset_index(drop=True),
                }),
                pd.DataFrame({
                    "GateV_backward": vg_bwd.reset_index(drop=True),
                    "DrainI_backward_active": id_bwd.reset_index(drop=True),
                    "DrainI_over_width_backward_A_per_um": np.abs(id_bwd.reset_index(drop=True)) / W,
                    "gm_backward_active": pd.Series(res["gm_bwd"]),
                    "mobility_backward_active": pd.Series(res["mu_bwd"]),
                    "source_index_backward": bwd["__source_index"].reset_index(drop=True),
                }),
            ], axis=1)

            plot_panel.download_button(
                "Download active analysis (CSV)",
                data=export_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{selected_sheet}_{operating_mode}_manual_removed.csv",
                mime="text/csv",
            )

