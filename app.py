
import io
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


def state_keys(file_id, sheet_name, mode):
    stem = f"{file_id}_{sheet_name}_{mode}"
    return {
        "removed_fwd": f"removed_fwd_{stem}",
        "removed_bwd": f"removed_bwd_{stem}",
        "remove_slider_fwd": f"remove_slider_fwd_{stem}",
        "remove_slider_bwd": f"remove_slider_bwd_{stem}",
        "peak_slider_fwd": f"peak_slider_fwd_{stem}",
        "peak_slider_bwd": f"peak_slider_bwd_{stem}",
    }


def initialize_removal_state(keys):
    if keys["removed_fwd"] not in st.session_state:
        st.session_state[keys["removed_fwd"]] = []
    if keys["removed_bwd"] not in st.session_state:
        st.session_state[keys["removed_bwd"]] = []


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

    # 최초 실행 또는 선택점이 제거되어 더 이상 존재하지 않을 때만 자동 최대점으로 재설정
    if keys["peak_slider_fwd"] not in st.session_state:
        st.session_state[keys["peak_slider_fwd"]] = float(fwd["GateV"].iloc[auto_idx_f])
    if keys["peak_slider_bwd"] not in st.session_state:
        st.session_state[keys["peak_slider_bwd"]] = float(bwd["GateV"].iloc[auto_idx_b])

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


def move_to_adjacent_vg(current_value, active_df, direction):
    """
    direction=-1: 정렬된 Vg에서 한 단계 감소
    direction=+1: 정렬된 Vg에서 한 단계 증가
    제거된 Vg는 목록에 없으므로 자동으로 건너뛴다.
    """
    values = sorted_unique_vg(active_df)
    if len(values) == 0:
        return float(current_value)

    nearest = int(np.argmin(np.abs(values - float(current_value))))
    target = int(np.clip(nearest + int(direction), 0, len(values) - 1))
    return float(values[target])


def initialize_slider_in_range(key, active_df, default_value):
    values = sorted_unique_vg(active_df)
    if len(values) == 0:
        return

    if key not in st.session_state:
        st.session_state[key] = float(default_value)

    current = float(st.session_state[key])
    nearest = int(np.argmin(np.abs(values - current)))
    st.session_state[key] = float(values[nearest])


def render_discrete_vg_control(
    title,
    slider_label,
    state_key,
    active_df,
    default_value,
    button_prefix,
):
    """
    - 버튼 | 실제 Vg slider | + 버튼
    슬라이더 step은 원 데이터의 대표 Vg 간격을 사용하고,
    버튼은 현재 남은 실제 Vg 목록에서 정확히 한 행씩 이동한다.
    """
    initialize_slider_in_range(state_key, active_df, default_value)

    values = sorted_unique_vg(active_df)
    if len(values) == 0:
        return np.nan

    diffs = np.diff(values)
    positive_diffs = np.abs(diffs[np.abs(diffs) > np.finfo(float).eps])
    step = float(np.min(positive_diffs)) if len(positive_diffs) else 0.5

    st.sidebar.markdown(f"**{title}**")
    minus_col, slider_col, plus_col = st.sidebar.columns([1, 5, 1])

    if minus_col.button("−", key=f"{button_prefix}_minus", use_container_width=True):
        st.session_state[state_key] = move_to_adjacent_vg(
            st.session_state[state_key], active_df, -1
        )
        st.rerun()

    slider_col.slider(
        slider_label,
        min_value=float(values.min()),
        max_value=float(values.max()),
        step=step,
        key=state_key,
        label_visibility="collapsed",
    )

    # 슬라이더가 실제 Vg 사이 값에 놓이면 가장 가까운 실제 데이터로 snap
    current = float(st.session_state[state_key])
    nearest = int(np.argmin(np.abs(values - current)))
    snapped = float(values[nearest])
    if not np.isclose(current, snapped):
        st.session_state[state_key] = snapped

    if plus_col.button("+", key=f"{button_prefix}_plus", use_container_width=True):
        st.session_state[state_key] = move_to_adjacent_vg(
            st.session_state[state_key], active_df, +1
        )
        st.rerun()

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
            st.rerun()

        if fcol2.button("Reset Fwd", use_container_width=True):
            st.session_state[keys["removed_fwd"]] = []
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
            st.rerun()

        if bcol2.button("Reset Bwd", use_container_width=True):
            st.session_state[keys["removed_bwd"]] = []
            st.rerun()

        removed_f_count = len(st.session_state[keys["removed_fwd"]])
        removed_b_count = len(st.session_state[keys["removed_bwd"]])
        st.sidebar.caption(
            f"Removed: Forward {removed_f_count} · Backward {removed_b_count}"
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
        o2.markdown(make_card("ON Current / Width", f"{params['on_density']:.3E} A/μm", "#5B5F97"), unsafe_allow_html=True)
        o3.markdown(make_card("OFF Current / Width", f"{params['off_density']:.3E} A/μm", "#5B5F97"), unsafe_allow_html=True)
        o4.markdown(make_card("Hysteresis", f"{params['hysteresis']:.2f} V", "#5B5F97"), unsafe_allow_html=True)

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
                "gm_forward_active": pd.Series(res["gm_fwd"]),
                "mobility_forward_active": pd.Series(res["mu_fwd"]),
                "source_index_forward": fwd["__source_index"].reset_index(drop=True),
            }),
            pd.DataFrame({
                "GateV_backward": vg_bwd.reset_index(drop=True),
                "DrainI_backward_active": id_bwd.reset_index(drop=True),
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
