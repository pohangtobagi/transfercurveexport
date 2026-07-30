
import io
import re
import uuid
from datetime import datetime
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

# ============================================================
# Session log / folder helpers
# ============================================================
def initialize_log_state():
    if "analysis_log_folders" not in st.session_state:
        st.session_state["analysis_log_folders"] = {}
    if "active_log_folder" not in st.session_state:
        st.session_state["active_log_folder"] = None


def create_log_folder(folder_name):
    name = str(folder_name).strip()
    if not name:
        return False, "폴더 이름을 입력하세요."
    folders = st.session_state["analysis_log_folders"]
    if name in folders:
        return False, "같은 이름의 폴더가 이미 있습니다."
    folders[name] = []
    st.session_state["active_log_folder"] = name
    return True, f"'{name}' 폴더를 생성했습니다."


def delete_log_entry(folder_name, entry_id):
    folders = st.session_state["analysis_log_folders"]
    if folder_name not in folders:
        return
    folders[folder_name] = [
        item for item in folders[folder_name]
        if item.get("_log_id") != entry_id
    ]


def clear_log_folder(folder_name):
    folders = st.session_state["analysis_log_folders"]
    if folder_name in folders:
        folders[folder_name] = []


def clear_all_logs():
    folders = st.session_state["analysis_log_folders"]
    for name in list(folders.keys()):
        folders[name] = []


def log_dataframe(folder_name):
    folders = st.session_state["analysis_log_folders"]
    records = folders.get(folder_name, [])
    if not records:
        return pd.DataFrame()

    rows = []
    for record in records:
        row = {
            key: value for key, value in record.items()
            if not key.startswith("_")
        }
        rows.append(row)
    return pd.DataFrame(rows)


def folder_excel_bytes(folder_name):
    df = log_dataframe(folder_name)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Parameters", index=False)

        # 간단한 summary 시트
        if not df.empty:
            numeric = df.select_dtypes(include=[np.number])
            if not numeric.empty:
                summary = pd.DataFrame({
                    "Parameter": numeric.columns,
                    "Mean": numeric.mean().values,
                    "Std": numeric.std().values,
                    "Min": numeric.min().values,
                    "Max": numeric.max().values,
                })
                summary.to_excel(writer, sheet_name="Summary", index=False)

    output.seek(0)
    return output.getvalue()


def safe_excel_filename(name):
    safe = re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip()
    return safe or "FET_Analysis_Log"


initialize_log_state()


# ============================================================
# Sidebar: Project manager
# ============================================================
initialize_log_state()

st.sidebar.header("Projects")
st.sidebar.caption("프로젝트를 생성하거나 선택한 뒤 분석을 진행하세요.")

project_name_input = st.sidebar.text_input(
    "New project name",
    key="new_project_name_sidebar",
    placeholder="예: 85K, Device batch A",
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
    active_project = st.sidebar.radio(
        "Project list",
        project_names,
        index=(
            project_names.index(st.session_state["active_log_folder"])
            if st.session_state.get("active_log_folder") in project_names
            else 0
        ),
        key="project_radio_sidebar",
    )
    st.session_state["active_log_folder"] = active_project

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
            log_name_col.caption(
                f"{log_idx}. {log_record.get('File', '')} · "
                f"{log_record.get('Sheet', '')}"
            )
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
        st.rerun()
else:
    active_project = None
    st.session_state["active_log_folder"] = None
    st.sidebar.info("먼저 개인 프로젝트를 생성하세요.")

st.sidebar.markdown("---")

# ============================================================
# Sidebar: device information
# ============================================================
st.sidebar.header("Device Information")
operating_mode = st.sidebar.radio("Operating Mode", ["Linear", "Saturation"])
st.sidebar.markdown("---")

W = st.sidebar.number_input("Width (μm)", value=1000.0, step=50.0)
L = st.sidebar.number_input("Length (μm)", value=100.0, step=50.0)
Cox_nf = st.sidebar.number_input("Capacitance (nF/cm⁻²)", value=34.5)
Cox = Cox_nf * 1e-9

# ============================================================
# Helpers
# ============================================================
def fix_inf(values):
    s = pd.Series(values).replace([np.inf, -np.inf], np.nan)
    return s.ffill().bfill().to_numpy()


def make_card(title, value, color):
    return f"""
    <div style='text-align:left; padding:5px 0;'>
        <p style='font-size:20px; margin-bottom:5px; color:#555;'>{title}</p>
        <p style='font-size:26px; font-weight:bold; color:{color}; margin:0; line-height:1.2;'>{value}</p>
    </div>
    """


def sci(value, digits=2):
    if not np.isfinite(value) or value <= 0:
        return "N/A"
    exp = int(np.floor(np.log10(value)))
    coef = value / (10 ** exp)
    return f"{coef:.{digits}f}E{exp}"


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

    st.sidebar.markdown(f"**{title}**")
    minus_col, slider_col, plus_col = st.sidebar.columns([1, 5, 1])

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

uploaded_file = st.file_uploader(
    "측정된 엑셀 파일을 업로드하세요",
    type=["xlsx", "xls"],
)

if uploaded_file:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    xls = pd.ExcelFile(uploaded_file)
    target_sheets = [
        s for s in xls.sheet_names
        if s == "Data" or s.lower().startswith("append")
    ]

    if not target_sheets:
        st.error("분석할 수 있는 시트('Data' 또는 'Append...')가 없습니다.")
        st.stop()

    st.sidebar.markdown("---")
    selected_sheet = st.sidebar.selectbox(
        "📂 Select Data Sheet",
        target_sheets + ["Average (All Sheets)"],
    )

    # ========================================================
    # Average mode
    # ========================================================
    if selected_sheet == "Average (All Sheets)":
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
        o2.markdown(make_card("ON Current / Width", f"{p['on_density']:.3E} A/μm", "#5B5F97"), unsafe_allow_html=True)
        o3.markdown(make_card("OFF Current / Width", f"{p['off_density']:.3E} A/μm", "#5B5F97"), unsafe_allow_html=True)
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

        # ====================================================
        # Peak point adjustment
        # ====================================================
        st.sidebar.markdown("---")
        st.sidebar.header("Mobility Peak Point Adjustment")
        st.sidebar.caption(
            "선택한 Vg 지점의 mobility와 Vth가 큰 카드에 반영됩니다. "
            "−/+ 버튼은 실제 측정 Vg 한 행씩 이동합니다."
        )

        peak_f_vg = render_discrete_vg_control(
            title="Forward peak Vg",
            slider_label="Forward peak Vg",
            state_key=keys["peak_slider_fwd"],
            active_df=fwd,
            default_value=float(fwd["GateV"].iloc[res["auto_idx_f"]]),
            button_prefix=f"peak_f_{file_id}_{selected_sheet}_{operating_mode}",
        )
        peak_b_vg = render_discrete_vg_control(
            title="Backward peak Vg",
            slider_label="Backward peak Vg",
            state_key=keys["peak_slider_bwd"],
            active_df=bwd,
            default_value=float(bwd["GateV"].iloc[res["auto_idx_b"]]),
            button_prefix=f"peak_b_{file_id}_{selected_sheet}_{operating_mode}",
        )

        # peak control 변경값을 즉시 parameter에 반영
        idx_f = int((fwd["GateV"] - peak_f_vg).abs().idxmin())
        idx_b = int((bwd["GateV"] - peak_b_vg).abs().idxmin())

        params = parameter_values(
            fwd["GateV"], fwd["DrainI_active"], res["gm_fwd"], res["mu_fwd"], idx_f,
            bwd["GateV"], bwd["DrainI_active"], res["gm_bwd"], res["mu_bwd"], idx_b,
            operating_mode, W,
        )

        st.sidebar.caption(
            f"Fwd μ = {params['mu_fwd']:.3g} cm²/V·s · "
            f"Bwd μ = {params['mu_bwd']:.3g} cm²/V·s"
        )

        auto_col_f, auto_col_b = st.sidebar.columns(2)
        if auto_col_f.button("Auto Max Fwd", use_container_width=True):
            st.session_state[keys["force_auto_peak_fwd"]] = True
            st.rerun()
        if auto_col_b.button("Auto Max Bwd", use_container_width=True):
            st.session_state[keys["force_auto_peak_bwd"]] = True
            st.rerun()

        # ====================================================
        # Manual removal controls
        # ====================================================
        st.sidebar.markdown("---")
        st.sidebar.header("Manual Mobility Point Removal")
        st.sidebar.caption(
            "제거할 mobility Vg를 선택한 뒤 Remove를 누르세요. "
            "해당 원래 행은 모든 plot과 parameter 계산에서 제외됩니다."
        )

        selected_f_vg = render_discrete_vg_control(
            title="Forward removal point",
            slider_label="Forward removal Vg",
            state_key=keys["remove_slider_fwd"],
            active_df=fwd,
            default_value=float(fwd["GateV"].iloc[res["auto_idx_f"]]),
            button_prefix=f"remove_f_{file_id}_{selected_sheet}_{operating_mode}",
        )
        selected_f_idx, selected_f_row = nearest_row_by_vg(fwd, selected_f_vg)
        selected_f_mu = float(res["mu_fwd"][selected_f_idx])
        st.sidebar.caption(
            f"Vg = {selected_f_row['GateV']:.2f} V · "
            f"Mobility = {selected_f_mu:.3g} cm²/V·s"
        )

        fcol1, fcol2 = st.sidebar.columns(2)
        if fcol1.button("Remove Fwd", use_container_width=True):
            source_idx = int(selected_f_row["__source_index"])
            removed = list(st.session_state[keys["removed_fwd"]])
            if source_idx not in removed:
                removed.append(source_idx)
                st.session_state[keys["removed_fwd"]] = removed
            st.session_state[keys["force_auto_peak_fwd"]] = True
            st.rerun()

        if fcol2.button("Reset Fwd", use_container_width=True):
            st.session_state[keys["removed_fwd"]] = []
            st.session_state[keys["force_auto_peak_fwd"]] = True
            st.rerun()

        selected_b_vg = render_discrete_vg_control(
            title="Backward removal point",
            slider_label="Backward removal Vg",
            state_key=keys["remove_slider_bwd"],
            active_df=bwd,
            default_value=float(bwd["GateV"].iloc[res["auto_idx_b"]]),
            button_prefix=f"remove_b_{file_id}_{selected_sheet}_{operating_mode}",
        )
        selected_b_idx, selected_b_row = nearest_row_by_vg(bwd, selected_b_vg)
        selected_b_mu = float(res["mu_bwd"][selected_b_idx])
        st.sidebar.caption(
            f"Vg = {selected_b_row['GateV']:.2f} V · "
            f"Mobility = {selected_b_mu:.3g} cm²/V·s"
        )

        bcol1, bcol2 = st.sidebar.columns(2)
        if bcol1.button("Remove Bwd", use_container_width=True):
            source_idx = int(selected_b_row["__source_index"])
            removed = list(st.session_state[keys["removed_bwd"]])
            if source_idx not in removed:
                removed.append(source_idx)
                st.session_state[keys["removed_bwd"]] = removed
            st.session_state[keys["force_auto_peak_bwd"]] = True
            st.rerun()

        if bcol2.button("Reset Bwd", use_container_width=True):
            st.session_state[keys["removed_bwd"]] = []
            st.session_state[keys["force_auto_peak_bwd"]] = True
            st.rerun()

        removed_f_count = len(st.session_state[keys["removed_fwd"]])
        removed_b_count = len(st.session_state[keys["removed_bwd"]])
        st.sidebar.caption(
            f"Removed: Forward {removed_f_count} · Backward {removed_b_count}"
        )

        # ====================================================
        # Transfer curve point inspection
        # ====================================================
        st.sidebar.markdown("---")
        st.sidebar.header("Transfer Current Point")
        st.sidebar.caption(
            "실제 측정 Vg 한 칸씩 이동하며 |DrainI|/Width를 확인합니다."
        )

        current_f_vg = render_discrete_vg_control(
            title="Forward transfer Vg",
            slider_label="Forward transfer Vg",
            state_key=keys["current_slider_fwd"],
            active_df=fwd,
            default_value=float(fwd["GateV"].iloc[0]),
            button_prefix=f"current_f_{file_id}_{selected_sheet}_{operating_mode}",
        )
        current_b_vg = render_discrete_vg_control(
            title="Backward transfer Vg",
            slider_label="Backward transfer Vg",
            state_key=keys["current_slider_bwd"],
            active_df=bwd,
            default_value=float(bwd["GateV"].iloc[0]),
            button_prefix=f"current_b_{file_id}_{selected_sheet}_{operating_mode}",
        )

        current_f_idx, current_f_row, current_f_density = current_density_at_vg(
            fwd, current_f_vg, W
        )
        current_b_idx, current_b_row, current_b_density = current_density_at_vg(
            bwd, current_b_vg, W
        )

        st.sidebar.caption(
            f"Fwd: {current_f_density:.2E} A/μm · "
            f"Bwd: {current_b_density:.2E} A/μm"
        )

        # ====================================================
        # Parameters: active values only
        # ====================================================
        st.markdown(
            f"<h3 style='color:#333;'>📊 Data Sheet: {selected_sheet} "
            f"({operating_mode})</h3>",
            unsafe_allow_html=True,
        )

        st.markdown("<h4 style='color:#6FADCF;'>Forward Sweep Parameters</h4>", unsafe_allow_html=True)
        f1, f2, f3, f4 = st.columns(4)
        f1.markdown(make_card("Peak Mobility", f"{params['mu_fwd']:.2f} cm²/V·s", "#2E60AB"), unsafe_allow_html=True)
        f2.markdown(make_card("Threshold Voltage (Vₜₕ)", f"{params['vth_fwd']:.2f} V", "#A23B72"), unsafe_allow_html=True)
        f3.markdown(make_card("Peak Point (Vg)", f"{params['peak_vg_fwd']:.1f} V", "#F18F01"), unsafe_allow_html=True)
        f4.markdown(make_card("SS", f"{params['ss_fwd']:.1f} mV/dec", "#18A558"), unsafe_allow_html=True)

        st.markdown("<h4 style='color:#F05650;'>Backward Sweep Parameters</h4>", unsafe_allow_html=True)
        b1, b2, b3, b4 = st.columns(4)
        b1.markdown(make_card("Peak Mobility", f"{params['mu_bwd']:.2f} cm²/V·s", "#2E60AB"), unsafe_allow_html=True)
        b2.markdown(make_card("Threshold Voltage (Vₜₕ)", f"{params['vth_bwd']:.2f} V", "#A23B72"), unsafe_allow_html=True)
        b3.markdown(make_card("Peak Point (Vg)", f"{params['peak_vg_bwd']:.1f} V", "#F18F01"), unsafe_allow_html=True)
        b4.markdown(make_card("SS", f"{params['ss_bwd']:.1f} mV/dec", "#18A558"), unsafe_allow_html=True)

        st.markdown("<h4>Overall Device Parameters</h4>", unsafe_allow_html=True)
        o1, o2, o3, o4 = st.columns(4)
        o1.markdown(make_card("On/Off Ratio", sci(params["onoff"]), "#5B5F97"), unsafe_allow_html=True)
        o2.markdown(make_card("ON Current / Width", f"{params['on_density']:.2E} A/μm", "#5B5F97"), unsafe_allow_html=True)
        o3.markdown(make_card("OFF Current / Width", f"{params['off_density']:.2E} A/μm", "#5B5F97"), unsafe_allow_html=True)
        o4.markdown(make_card("Hysteresis", f"{params['hysteresis']:.2f} V", "#5B5F97"), unsafe_allow_html=True)

        st.markdown("<h4 style='color:#555;'>Selected Transfer Current Density</h4>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(make_card("Forward Vg", f"{float(current_f_row['GateV']):.2f} V", "#2E60AB"), unsafe_allow_html=True)
        c2.markdown(make_card("Forward |Id| / W", f"{current_f_density:.2E} A/μm", "#2E60AB"), unsafe_allow_html=True)
        c3.markdown(make_card("Backward Vg", f"{float(current_b_row['GateV']):.2f} V", "#F05650"), unsafe_allow_html=True)
        c4.markdown(make_card("Backward |Id| / W", f"{current_b_density:.2E} A/μm", "#F05650"), unsafe_allow_html=True)

        # ====================================================
        # Save current result to selected folder
        # ====================================================
        st.markdown("<h4>Save Analysis Result</h4>", unsafe_allow_html=True)
        save_col1, save_col2 = st.columns([3, 1])

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
            log_entry = {
                "_log_id": str(uuid.uuid4()),
                "Saved at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "File": uploaded_file.name,
                "Sheet": selected_sheet,
                "Operating mode": operating_mode,
                "Width (μm)": float(W),
                "Length (μm)": float(L),
                "Cox (nF/cm²)": float(Cox_nf),
                "Drain voltage (V)": float(res["vd"]),
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
            st.success(f"'{current_project}' 프로젝트에 로그를 저장했습니다.")
            st.rerun()

        st.markdown("---")

        # ====================================================
        # Plot: active data only
        # ====================================================
        graph3_title = (
            "3. Transconductance (Gₘ)"
            if operating_mode == "Linear"
            else "3. d(√I<sub>D</sub>)/dV<sub>G</sub>"
        )
        graph4_title = (
            "4. Linear Mobility"
            if operating_mode == "Linear"
            else "4. Saturation Mobility"
        )

        fig = make_subplots(
            rows=2,
            cols=2,
            subplot_titles=(
                "1. Transfer (Log Scale)",
                "2. Transfer (Linear Scale)",
                graph3_title,
                graph4_title,
            ),
            horizontal_spacing=0.25,
            vertical_spacing=0.25,
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

        # Gate leakage only in raw mode because manually removed rows no longer align
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
        ), row=1, col=2)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=np.abs(id_bwd),
            name="Backward", line=dict(color=color_bwd),
        ), row=1, col=2)

        # 선택한 transfer-current 지점을 log/linear transfer plot에 표시
        for row_num, col_num in ((1, 1), (1, 2)):
            fig.add_trace(go.Scatter(
                x=[float(current_f_row["GateV"])],
                y=[abs(float(current_f_row["DrainI_active"]))],
                mode="markers",
                marker=dict(symbol="circle-open", size=11, color="black", line=dict(width=2)),
                name="Fwd current target",
                showlegend=False,
            ), row=row_num, col=col_num)
            fig.add_trace(go.Scatter(
                x=[float(current_b_row["GateV"])],
                y=[abs(float(current_b_row["DrainI_active"]))],
                mode="markers",
                marker=dict(symbol="square-open", size=11, color="black", line=dict(width=2)),
                name="Bwd current target",
                showlegend=False,
            ), row=row_num, col=col_num)

        # Gm
        fig.add_trace(go.Scatter(
            x=vg_fwd, y=np.abs(res["gm_fwd"]),
            name="Forward", line=dict(color=color_fwd),
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=np.abs(res["gm_bwd"]),
            name="Backward", line=dict(color=color_bwd),
        ), row=2, col=1)

        # Mobility
        fig.add_trace(go.Scatter(
            x=vg_fwd, y=res["mu_fwd"],
            name="Forward", line=dict(color=color_fwd),
        ), row=2, col=2)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=res["mu_bwd"],
            name="Backward", line=dict(color=color_bwd),
        ), row=2, col=2)

        # Removal candidates shown only on mobility plot
        fig.add_trace(go.Scatter(
            x=[float(selected_f_row["GateV"])],
            y=[selected_f_mu],
            mode="markers",
            name="Fwd removal target",
            marker=dict(symbol="x", size=13, color="black", line=dict(width=2)),
            showlegend=False,
        ), row=2, col=2)

        fig.add_trace(go.Scatter(
            x=[float(selected_b_row["GateV"])],
            y=[selected_b_mu],
            mode="markers",
            name="Bwd removal target",
            marker=dict(symbol="x", size=13, color="black", line=dict(width=2)),
            showlegend=False,
        ), row=2, col=2)

        # Automatically re-detected mobility maxima
        peak_f_vg = params["peak_vg_fwd"]
        peak_b_vg = params["peak_vg_bwd"]

        for col in (1, 2):
            fig.add_vline(
                x=peak_f_vg,
                line_width=1.5,
                line_dash="dash",
                line_color=color_fwd,
                row=2,
                col=col,
            )
            fig.add_vline(
                x=peak_b_vg,
                line_width=1.5,
                line_dash="dash",
                line_color=color_bwd,
                row=2,
                col=col,
            )

        vd_formatted = f"{res['vd']:.2f}".rstrip("0").rstrip(".")
        fig.add_annotation(
            x=0.001,
            y=0.001,
            xref="x domain",
            yref="y domain",
            text=f"<b>V<sub>D</sub> = {vd_formatted} V</b>",
            showarrow=False,
            font=dict(size=12, color="black"),
            row=1,
            col=1,
        )

        common_axis = dict(
            ticks="outside",
            tickwidth=1.5,
            tickcolor="black",
            ticklen=8,
            showline=True,
            linewidth=1.5,
            linecolor="black",
            mirror=True,
            showgrid=True,
            gridwidth=1,
            gridcolor="lightgray",
            griddash="dot",
            zeroline=False,
            title_font=dict(size=20),
            tickfont=dict(size=14),
        )

        vg_all = pd.concat([vg_fwd, vg_bwd])
        vg_range = abs(vg_all.max() - vg_all.min())
        dynamic_dtick = 2.5 if vg_range <= 10 else 10

        y3 = (
            "Gₘ (S)"
            if operating_mode == "Linear"
            else "d(√I<sub>D</sub>)/dV<sub>G</sub> (A<sup>0.5</sup>/V)"
        )
        y4 = (
            "Linear Mobility (cm²/V·s)"
            if operating_mode == "Linear"
            else "Saturation Mobility (cm²/V·s)"
        )

        fig.update_xaxes(
            title_text="Gate Voltage (V)",
            dtick=dynamic_dtick,
            **common_axis,
        )
        fig.update_yaxes(**common_axis)
        fig.update_yaxes(
            title_text="Drain Current (A)",
            type="log",
            row=1,
            col=1,
        )
        fig.update_yaxes(
            title_text="Drain Current (A)",
            row=1,
            col=2,
        )
        fig.update_yaxes(
            title_text=y3,
            row=2,
            col=1,
        )
        fig.update_yaxes(
            title_text=y4,
            row=2,
            col=2,
        )

        fig.update_layout(
            width=1000,
            height=1000,
            autosize=False,
            template="plotly_white",
            margin=dict(t=120, b=80, l=100, r=100),
        )
        fig.update_annotations(font_size=20)

        st.plotly_chart(fig, use_container_width=False)

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

        st.download_button(
            "Download active analysis (CSV)",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{selected_sheet}_{operating_mode}_manual_removed.csv",
            mime="text/csv",
        )

