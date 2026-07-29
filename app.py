
import io
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.signal import savgol_filter
from scipy.ndimage import median_filter

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

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.header("Device Information")
operating_mode = st.sidebar.radio("Operating Mode", ["Linear", "Saturation"])
st.sidebar.markdown("---")

W = st.sidebar.number_input("Width (μm)", value=1000.0, step=50.0)
L = st.sidebar.number_input("Length (μm)", value=100.0, step=50.0)
Cox_nf = st.sidebar.number_input("Capacitance (nF/cm⁻²)", value=34.5)
Cox = Cox_nf * 1e-9

st.sidebar.markdown("---")
st.sidebar.header("Data Cleaning")
apply_smoothing = st.sidebar.checkbox("Remove spikes + Smooth", value=False)

if apply_smoothing:
    smooth_center = st.sidebar.number_input("Center Vg (V)", value=0.0, step=0.5)
    smooth_half_width = st.sidebar.number_input("Cleaning range (±V)", min_value=0.0, value=5.0, step=0.5)
    smooth_kernel = st.sidebar.slider("Spike detection window", 3, 21, 5, 2)
    smooth_z = st.sidebar.slider(
        "Upward spike threshold", 2.0, 12.0, 4.0, 0.5,
        help="작을수록 위로 튀는 점을 더 많이 제거합니다."
    )
    smooth_window = st.sidebar.slider("Smoothing window", 3, 31, 7, 2)
    smooth_polyorder = st.sidebar.slider("Polynomial order", 1, 4, 2)
    smooth_log_domain = st.sidebar.checkbox("Smooth in log(|Id|)", value=True)
else:
    smooth_center = 0.0
    smooth_half_width = 5.0
    smooth_kernel = 5
    smooth_z = 4.0
    smooth_window = 7
    smooth_polyorder = 2
    smooth_log_domain = True


# -----------------------------
# Helpers
# -----------------------------
def fix_inf(values):
    s = pd.Series(values).replace([np.inf, -np.inf], np.nan)
    return s.ffill().bfill().to_numpy()


def calculate_ss(id_vals, vg_vals):
    """
    기존 코드와 동일한 방식:
    전체 sweep에서 max |d(log10|Id|)/dVg|의 역수.
    """
    id_vals = np.asarray(id_vals, dtype=float)
    vg_vals = np.asarray(vg_vals, dtype=float)
    valid = np.isfinite(id_vals) & np.isfinite(vg_vals)
    if valid.sum() < 3:
        return np.nan

    id_vals = id_vals[valid]
    vg_vals = vg_vals[valid]
    log_id = np.log10(np.abs(id_vals) + 1e-15)
    slope = np.abs(np.gradient(log_id, vg_vals))
    if len(slope) >= 3:
        slope = np.convolve(slope, np.ones(3) / 3, mode="same")
    slope = slope[np.isfinite(slope) & (slope > 0)]
    return 1000.0 / np.max(slope) if len(slope) else np.nan


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


def detect_upward_spikes(transformed, kernel_size=5, z_threshold=4.0):
    """
    위쪽으로만 갑자기 튀는 점을 검출.
    검출된 점은 smoothing 입력과 최종 plot에서 완전히 제외한다.
    """
    y = np.asarray(transformed, dtype=float)
    valid = np.isfinite(y)
    mask = np.zeros(len(y), dtype=bool)

    if valid.sum() < 5:
        return mask

    work = y.copy()
    idx = np.arange(len(work))
    work[~valid] = np.interp(idx[~valid], idx[valid], work[valid])

    kernel_size = max(3, int(kernel_size))
    if kernel_size % 2 == 0:
        kernel_size += 1
    max_kernel = len(work) if len(work) % 2 else len(work) - 1
    kernel_size = min(kernel_size, max_kernel)
    if kernel_size < 3:
        return mask

    local_med = median_filter(work, size=kernel_size, mode="nearest")
    residual = work - local_med
    med = np.median(residual)
    mad = np.median(np.abs(residual - med))
    sigma = 1.4826 * mad

    if not np.isfinite(sigma) or sigma <= 0:
        d = np.diff(work)
        dmad = np.median(np.abs(d - np.median(d))) if len(d) else 0.0
        sigma = max(1.4826 * dmad, np.finfo(float).eps)

    # Local median보다 위에 있고, 양쪽 이웃 연결선보다도 위에 있는 점
    neighbor = local_med.copy()
    if len(work) >= 3:
        neighbor[1:-1] = 0.5 * (work[:-2] + work[2:])

    mask = (
        (residual > med + z_threshold * sigma)
        & ((work - neighbor) > 0.5 * z_threshold * sigma)
        & valid
    )

    # 양 끝은 자동 제거하지 않음
    mask[0] = False
    mask[-1] = False
    return mask


def remove_spikes_and_smooth(vg, current):
    """
    1) 지정 범위에서 upward spike 검출
    2) 해당 행을 데이터에서 완전히 제거
    3) 남은 점끼리만 Savitzky-Golay smoothing
    4) 제거된 Vg는 최종 plot/calculation에 사용하지 않음
    """
    vg = np.asarray(vg, dtype=float)
    current = np.asarray(current, dtype=float)

    base_valid = np.isfinite(vg) & np.isfinite(current)
    region = base_valid & (np.abs(vg - smooth_center) <= smooth_half_width)

    transformed = np.full(len(current), np.nan, dtype=float)
    sign = np.sign(current)
    sign[sign == 0] = 1.0

    if smooth_log_domain:
        mag = np.abs(current)
        nz = mag[base_valid & (mag > 0)]
        floor = max(np.min(nz) * 0.1, np.finfo(float).tiny) if len(nz) else np.finfo(float).tiny
        transformed[base_valid] = np.log10(np.maximum(mag[base_valid], floor))
    else:
        transformed[base_valid] = current[base_valid]

    region_idx = np.where(region)[0]
    spike_mask = np.zeros(len(current), dtype=bool)

    if len(region_idx) >= 5:
        local_spikes = detect_upward_spikes(
            transformed[region_idx],
            kernel_size=smooth_kernel,
            z_threshold=smooth_z,
        )
        spike_mask[region_idx] = local_spikes

    keep = base_valid & (~spike_mask)
    vg_clean = vg[keep]
    transformed_clean = transformed[keep]
    sign_clean = sign[keep]

    # Sweep order 유지. 남은 점들끼리만 smoothing.
    corrected = transformed_clean.copy()
    n = len(corrected)
    window = int(smooth_window)
    if window % 2 == 0:
        window += 1
    max_window = n if n % 2 else n - 1
    window = min(window, max_window)

    if n >= 3 and window >= 3:
        poly = min(int(smooth_polyorder), window - 1)
        if window > poly:
            corrected = savgol_filter(
                corrected,
                window_length=window,
                polyorder=poly,
                mode="interp",
            )

    if smooth_log_domain:
        current_clean = sign_clean * np.power(10.0, corrected)
    else:
        current_clean = corrected

    return (
        pd.Series(vg_clean).reset_index(drop=True),
        pd.Series(current_clean).reset_index(drop=True),
        spike_mask,
    )


def calc_curves(vg, current, mode, w, l, cox, vd):
    vg_arr = np.asarray(vg, dtype=float)
    id_arr = np.asarray(current, dtype=float)

    if len(vg_arr) < 3:
        return np.full(len(vg_arr), np.nan), np.full(len(vg_arr), np.nan)

    if mode == "Linear":
        gm = fix_inf(np.gradient(id_arr, vg_arr))
        mobility = np.abs(gm) * l / (w * cox * abs(vd))
    else:
        sqrt_id = np.sqrt(np.abs(id_arr))
        gm = fix_inf(np.gradient(sqrt_id, vg_arr))
        mobility = (2 * l / (w * cox)) * gm**2

    return gm, mobility


def auto_peak_index(curve):
    values = np.asarray(curve, dtype=float)
    if len(values) == 0:
        return 0
    finite = np.where(np.isfinite(values), np.abs(values), -np.inf)
    if len(finite) > 5:
        local = finite[2:-2]
        return int(np.argmax(local) + 2)
    return int(np.argmax(finite))


def compute_parameters(vg_fwd, id_fwd, vg_bwd, id_bwd, mode, w, l, cox, vd):
    gm_fwd, mu_fwd = calc_curves(vg_fwd, id_fwd, mode, w, l, cox, vd)
    gm_bwd, mu_bwd = calc_curves(vg_bwd, id_bwd, mode, w, l, cox, vd)

    idx_f_auto = auto_peak_index(mu_fwd)
    idx_b_auto = auto_peak_index(mu_bwd)

    return gm_fwd, mu_fwd, gm_bwd, mu_bwd, idx_f_auto, idx_b_auto


def parameter_values(
    vg_fwd, id_fwd, gm_fwd, mu_fwd, idx_f,
    vg_bwd, id_bwd, gm_bwd, mu_bwd, idx_b,
    mode, w
):
    def safe_vth(vg, current, gm, idx):
        if len(vg) == 0 or idx >= len(vg):
            return np.nan
        g = gm[idx]
        if not np.isfinite(g) or abs(g) <= np.finfo(float).eps:
            return np.nan
        numerator = np.sqrt(abs(current.iloc[idx])) if mode == "Saturation" else current.iloc[idx]
        return float(vg.iloc[idx] - numerator / g)

    vth_f = safe_vth(vg_fwd, id_fwd, gm_fwd, idx_f)
    vth_b = safe_vth(vg_bwd, id_bwd, gm_bwd, idx_b)

    full = np.concatenate([np.asarray(id_fwd), np.asarray(id_bwd)[1:]])
    finite_abs = np.abs(full[np.isfinite(full)])
    positive = finite_abs[finite_abs > 0]

    on_current = float(np.max(finite_abs)) if len(finite_abs) else np.nan
    off_current = float(np.min(positive)) if len(positive) else np.nan

    return {
        "mu_fwd": float(mu_fwd[idx_f]) if len(mu_fwd) else np.nan,
        "mu_bwd": float(mu_bwd[idx_b]) if len(mu_bwd) else np.nan,
        "vth_fwd": vth_f,
        "vth_bwd": vth_b,
        "peak_vg_fwd": float(vg_fwd.iloc[idx_f]) if len(vg_fwd) else np.nan,
        "peak_vg_bwd": float(vg_bwd.iloc[idx_b]) if len(vg_bwd) else np.nan,
        "ss_fwd": calculate_ss(id_fwd, vg_fwd),
        "ss_bwd": calculate_ss(id_bwd, vg_bwd),
        "hysteresis": abs(vth_f - vth_b) if np.isfinite(vth_f) and np.isfinite(vth_b) else np.nan,
        "onoff": on_current / off_current if np.isfinite(off_current) and off_current > 0 else np.nan,
        "on_density": on_current / w if np.isfinite(on_current) else np.nan,
        "off_density": off_current / w if np.isfinite(off_current) else np.nan,
    }


def split_sweep(df):
    vg = pd.to_numeric(df["GateV"], errors="coerce").reset_index(drop=True)
    current = pd.to_numeric(df["DrainI"], errors="coerce").reset_index(drop=True)

    if abs(vg.max() - vg.iloc[0]) > abs(vg.min() - vg.iloc[0]):
        turning = int(vg.idxmax())
    else:
        turning = int(vg.idxmin())

    return (
        vg.iloc[:turning + 1].reset_index(drop=True),
        current.iloc[:turning + 1].reset_index(drop=True),
        vg.iloc[turning:].reset_index(drop=True),
        current.iloc[turning:].reset_index(drop=True),
    )


def analyze_sheet(df, file_id, sheet_name):
    if W <= 0 or L <= 0 or Cox <= 0:
        raise ValueError("Width, Length, Capacitance는 모두 0보다 커야 합니다.")

    vd_values = pd.to_numeric(df["DrainV"], errors="coerce").dropna()
    if vd_values.empty:
        raise ValueError("DrainV 값이 없습니다.")
    vd = float(vd_values.iloc[0])
    if operating_mode == "Linear" and abs(vd) <= np.finfo(float).eps:
        raise ValueError("Linear mode에서는 DrainV가 0이 아니어야 합니다.")

    vg_fwd_raw, id_fwd_raw, vg_bwd_raw, id_bwd_raw = split_sweep(df)

    if apply_smoothing:
        vg_fwd, id_fwd, spike_fwd = remove_spikes_and_smooth(vg_fwd_raw, id_fwd_raw)
        vg_bwd, id_bwd, spike_bwd = remove_spikes_and_smooth(vg_bwd_raw, id_bwd_raw)
    else:
        vg_fwd, id_fwd = vg_fwd_raw.copy(), id_fwd_raw.copy()
        vg_bwd, id_bwd = vg_bwd_raw.copy(), id_bwd_raw.copy()
        spike_fwd = np.zeros(len(vg_fwd_raw), dtype=bool)
        spike_bwd = np.zeros(len(vg_bwd_raw), dtype=bool)

    gm_fwd, mu_fwd, gm_bwd, mu_bwd, auto_f, auto_b = compute_parameters(
        vg_fwd, id_fwd, vg_bwd, id_bwd,
        operating_mode, W, L, Cox, vd
    )

    # Smoothing 상태별로 별도 세션 키 사용:
    # 버튼을 켜면 cleaned curve에서 peak를 새로 자동 탐색한다.
    state_tag = "clean" if apply_smoothing else "raw"
    master_f = f"peak_f_{file_id}_{sheet_name}_{operating_mode}_{state_tag}"
    master_b = f"peak_b_{file_id}_{sheet_name}_{operating_mode}_{state_tag}"

    if master_f not in st.session_state:
        st.session_state[master_f] = float(vg_fwd.iloc[auto_f])
    if master_b not in st.session_state:
        st.session_state[master_b] = float(vg_bwd.iloc[auto_b])

    target_f = float(st.session_state[master_f])
    target_b = float(st.session_state[master_b])
    idx_f = int((vg_fwd - target_f).abs().idxmin())
    idx_b = int((vg_bwd - target_b).abs().idxmin())

    params = parameter_values(
        vg_fwd, id_fwd, gm_fwd, mu_fwd, idx_f,
        vg_bwd, id_bwd, gm_bwd, mu_bwd, idx_b,
        operating_mode, W
    )

    return {
        "vd": vd,
        "vg_fwd": vg_fwd,
        "id_fwd": id_fwd,
        "vg_bwd": vg_bwd,
        "id_bwd": id_bwd,
        "vg_fwd_raw": vg_fwd_raw,
        "id_fwd_raw": id_fwd_raw,
        "vg_bwd_raw": vg_bwd_raw,
        "id_bwd_raw": id_bwd_raw,
        "spike_fwd": spike_fwd,
        "spike_bwd": spike_bwd,
        "gm_fwd": gm_fwd,
        "gm_bwd": gm_bwd,
        "mu_fwd": mu_fwd,
        "mu_bwd": mu_bwd,
        "idx_f": idx_f,
        "idx_b": idx_b,
        "master_f": master_f,
        "master_b": master_b,
        "params": params,
    }


# -----------------------------
# File upload
# -----------------------------
uploaded_file = st.file_uploader("측정된 엑셀 파일을 업로드하세요", type=["xlsx", "xls"])

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
        target_sheets + ["Average (All Sheets)"]
    )

    # -----------------------------
    # Average mode
    # -----------------------------
    if selected_sheet == "Average (All Sheets)":
        rows = []
        for sheet in target_sheets:
            df = pd.read_excel(uploaded_file, sheet_name=sheet)
            if {"GateV", "DrainI", "DrainV"}.issubset(df.columns):
                try:
                    result = analyze_sheet(df, file_id, sheet)
                    row = {"Sheet": sheet, **result["params"]}
                    rows.append(row)
                except Exception:
                    pass

        if not rows:
            st.error("유효한 시트가 없습니다.")
            st.stop()

        stats = pd.DataFrame(rows)
        suffix = "Cleaned" if apply_smoothing else "Raw"
        st.markdown(f"### 📊 {suffix} Statistics ({operating_mode})")

        p = {
            key: stats[key].mean()
            for key in [
                "mu_fwd", "mu_bwd", "vth_fwd", "vth_bwd",
                "ss_fwd", "ss_bwd", "hysteresis",
                "onoff", "on_density", "off_density"
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

    # -----------------------------
    # Single sheet mode
    # -----------------------------
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

        # Peak sliders: active dataset only
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**Peak Point Adjustment ({selected_sheet})**")

        vg_fwd = res["vg_fwd"]
        vg_bwd = res["vg_bwd"]
        step_f = float(np.median(np.abs(np.diff(vg_fwd)))) if len(vg_fwd) > 1 else 0.5
        step_b = float(np.median(np.abs(np.diff(vg_bwd)))) if len(vg_bwd) > 1 else 0.5
        step_f = step_f if np.isfinite(step_f) and step_f > 0 else 0.5
        step_b = step_b if np.isfinite(step_b) and step_b > 0 else 0.5

        slider_f = f"slider_{res['master_f']}"
        slider_b = f"slider_{res['master_b']}"

        if slider_f not in st.session_state:
            st.session_state[slider_f] = st.session_state[res["master_f"]]
        if slider_b not in st.session_state:
            st.session_state[slider_b] = st.session_state[res["master_b"]]

        def sync_f():
            st.session_state[res["master_f"]] = st.session_state[slider_f]

        def sync_b():
            st.session_state[res["master_b"]] = st.session_state[slider_b]

        st.sidebar.slider(
            "Forward Vg Point",
            min_value=float(vg_fwd.min()),
            max_value=float(vg_fwd.max()),
            step=step_f,
            key=slider_f,
            on_change=sync_f,
        )
        st.sidebar.slider(
            "Backward Vg Point",
            min_value=float(vg_bwd.min()),
            max_value=float(vg_bwd.max()),
            step=step_b,
            key=slider_b,
            on_change=sync_b,
        )

        # Rerun calculation after slider values
        idx_f = int((vg_fwd - st.session_state[res["master_f"]]).abs().idxmin())
        idx_b = int((vg_bwd - st.session_state[res["master_b"]]).abs().idxmin())
        params = parameter_values(
            vg_fwd, res["id_fwd"], res["gm_fwd"], res["mu_fwd"], idx_f,
            vg_bwd, res["id_bwd"], res["gm_bwd"], res["mu_bwd"], idx_b,
            operating_mode, W
        )

        mode_label = "Cleaned + Smoothed" if apply_smoothing else "Raw"
        st.markdown(
            f"<h3 style='color:#333;'>📊 Data Sheet: {selected_sheet} "
            f"({operating_mode}, {mode_label})</h3>",
            unsafe_allow_html=True
        )

        # Only large cards. Values switch in place.
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

        if apply_smoothing:
            removed = int(np.sum(res["spike_fwd"]) + np.sum(res["spike_bwd"]))
            st.caption(
                f"Removed upward spikes: {removed}. "
                "검출된 점은 plot과 parameter 계산에서 완전히 제외되었습니다."
            )

        st.markdown("---")

        # Plot active dataset only
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
            rows=2, cols=2,
            subplot_titles=(
                "1. Transfer (Log Scale)",
                "2. Transfer (Linear Scale)",
                graph3_title,
                graph4_title,
            ),
            horizontal_spacing=0.25,
            vertical_spacing=0.25,
        )

        color_fwd, color_bwd = "blue", "red"

        fig.add_trace(go.Scatter(
            x=vg_fwd, y=np.abs(res["id_fwd"]),
            name="Forward", line=dict(color=color_fwd)
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=np.abs(res["id_bwd"]),
            name="Backward", line=dict(color=color_bwd)
        ), row=1, col=1)

        has_ig = "GateI" in df.columns
        if has_ig and not apply_smoothing:
            ig = pd.to_numeric(df["GateI"], errors="coerce")
            turning = len(res["vg_fwd_raw"]) - 1
            ig_f = ig.iloc[:turning + 1].reset_index(drop=True)
            ig_b = ig.iloc[turning:].reset_index(drop=True)
            fig.add_trace(go.Scatter(
                x=res["vg_fwd_raw"], y=np.abs(ig_f),
                name="Ig (Fwd)", line=dict(color="dimgray", dash="dot"),
                showlegend=False
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=res["vg_bwd_raw"], y=np.abs(ig_b),
                name="Ig (Bwd)", line=dict(color="dimgray", dash="dot"),
                showlegend=False
            ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=vg_fwd, y=np.abs(res["id_fwd"]),
            name="Forward", line=dict(color=color_fwd)
        ), row=1, col=2)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=np.abs(res["id_bwd"]),
            name="Backward", line=dict(color=color_bwd)
        ), row=1, col=2)

        fig.add_trace(go.Scatter(
            x=vg_fwd, y=np.abs(res["gm_fwd"]),
            name="Forward", line=dict(color=color_fwd)
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=np.abs(res["gm_bwd"]),
            name="Backward", line=dict(color=color_bwd)
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=vg_fwd, y=res["mu_fwd"],
            name="Forward", line=dict(color=color_fwd)
        ), row=2, col=2)
        fig.add_trace(go.Scatter(
            x=vg_bwd, y=res["mu_bwd"],
            name="Backward", line=dict(color=color_bwd)
        ), row=2, col=2)

        peak_f_vg = float(vg_fwd.iloc[idx_f])
        peak_b_vg = float(vg_bwd.iloc[idx_b])
        for col in (1, 2):
            fig.add_vline(x=peak_f_vg, line_width=1.5, line_dash="dash", line_color=color_fwd, row=2, col=col)
            fig.add_vline(x=peak_b_vg, line_width=1.5, line_dash="dash", line_color=color_bwd, row=2, col=col)

        vd_formatted = f"{res['vd']:.2f}".rstrip("0").rstrip(".")
        fig.add_annotation(
            x=0.001, y=0.001, xref="x domain", yref="y domain",
            text=f"<b>V<sub>D</sub> = {vd_formatted} V</b>",
            showarrow=False, font=dict(size=12, color="black"),
            row=1, col=1
        )

        common_axis = dict(
            ticks="outside", tickwidth=1.5, tickcolor="black", ticklen=8,
            showline=True, linewidth=1.5, linecolor="black", mirror=True,
            showgrid=True, gridwidth=1, gridcolor="lightgray",
            griddash="dot", zeroline=False,
            title_font=dict(size=20), tickfont=dict(size=14),
        )

        vg_all = pd.concat([vg_fwd, vg_bwd])
        vg_range = abs(vg_all.max() - vg_all.min())
        dynamic_dtick = 2.5 if vg_range <= 10 else 10

        y3 = "Gₘ (S)" if operating_mode == "Linear" else "d(√I<sub>D</sub>)/dV<sub>G</sub> (A<sup>0.5</sup>/V)"
        y4 = "Linear Mobility (cm²/V·s)" if operating_mode == "Linear" else "Saturation Mobility (cm²/V·s)"

        fig.update_xaxes(title_text="Gate Voltage (V)", dtick=dynamic_dtick, **common_axis)
        fig.update_yaxes(**common_axis)
        fig.update_yaxes(title_text="Drain Current (A)", type="log", row=1, col=1)
        fig.update_yaxes(title_text="Drain Current (A)", row=1, col=2)
        fig.update_yaxes(title_text=y3, row=2, col=1)
        fig.update_yaxes(title_text=y4, row=2, col=2)

        fig.update_layout(
            width=1000, height=1000, autosize=False,
            template="plotly_white",
            margin=dict(t=120, b=80, l=100, r=100),
        )
        fig.update_annotations(font_size=20)

        st.plotly_chart(fig, use_container_width=False)

        export_df = pd.concat([
            pd.DataFrame({
                "GateV_forward": vg_fwd,
                "DrainI_forward_active": res["id_fwd"],
                "gm_forward_active": res["gm_fwd"],
                "mobility_forward_active": res["mu_fwd"],
            }),
            pd.DataFrame({
                "GateV_backward": vg_bwd,
                "DrainI_backward_active": res["id_bwd"],
                "gm_backward_active": res["gm_bwd"],
                "mobility_backward_active": res["mu_bwd"],
            }),
        ], axis=1)

        st.download_button(
            "Download active analysis (CSV)",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{selected_sheet}_{operating_mode}_{'cleaned' if apply_smoothing else 'raw'}.csv",
            mime="text/csv",
        )
