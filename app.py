
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
apply_smoothing = st.sidebar.checkbox(
    "Remove derivative spikes + Smooth",
    value=False,
    key="apply_smoothing"
)

# 설정 위젯은 ON/OFF와 관계없이 계속 표시하여 입력값이 사라지지 않게 함
clean_full_sweep = st.sidebar.checkbox(
    "Detect spikes over full sweep",
    value=True,
    key="clean_full_sweep",
    help="체크하면 사진처럼 -20 V 부근 등에 나타나는 spike도 전체 sweep에서 검출합니다."
)
smooth_center = st.sidebar.number_input(
    "Center Vg (V)", value=0.0, step=0.5, key="smooth_center"
)
smooth_half_width = st.sidebar.number_input(
    "Cleaning range (±V)", min_value=0.0, value=5.0, step=0.5,
    key="smooth_half_width",
    disabled=clean_full_sweep,
)
smooth_kernel = st.sidebar.slider(
    "Spike detection window", 3, 21, 5, 2, key="smooth_kernel"
)
smooth_z = st.sidebar.slider(
    "Derivative spike threshold", 2.0, 12.0, 4.0, 0.5,
    key="smooth_z",
    help="작을수록 Gm/mobility의 좁고 높은 이상 peak를 더 적극적으로 제거합니다."
)
smooth_window = st.sidebar.slider(
    "Smoothing window", 3, 31, 7, 2, key="smooth_window"
)
smooth_polyorder = st.sidebar.slider(
    "Polynomial order", 1, 4, 2, key="smooth_polyorder"
)
smooth_log_domain = st.sidebar.checkbox(
    "Smooth in log(|Id|)", value=True, key="smooth_log_domain"
)

# Cleaning 관련 설정이 바뀌면 active curve의 mobility peak를 다시 자동 탐색
cleaning_signature = (
    bool(apply_smoothing), bool(clean_full_sweep), float(smooth_center),
    float(smooth_half_width), int(smooth_kernel), float(smooth_z),
    int(smooth_window), int(smooth_polyorder), bool(smooth_log_domain),
    operating_mode, float(W), float(L), float(Cox_nf),
)
_previous_signature = st.session_state.get("_cleaning_signature")
force_auto_peak = _previous_signature != cleaning_signature
st.session_state["_cleaning_signature"] = cleaning_signature


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


def _robust_sigma(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.finfo(float).eps
    med = np.median(values)
    mad = np.median(np.abs(values - med))
    sigma = 1.4826 * mad
    return max(float(sigma), np.finfo(float).eps)


def detect_derivative_spike_points(vg, transformed, kernel_size=5, z_threshold=4.0):
    """
    Gm/mobility에 생기는 좁고 높은 peak의 원인이 되는 원래 Id 점을 찾는다.

    1) transformed Id의 1차 미분에서 국소 이상치를 찾고
    2) 원래 Id 점이 양쪽 이웃 연결선보다 위로 솟았는지 확인한 뒤
    3) 해당 Id 행 자체를 제거 대상으로 반환한다.
    """
    vg = np.asarray(vg, dtype=float)
    y = np.asarray(transformed, dtype=float)
    n = len(y)
    remove = np.zeros(n, dtype=bool)
    valid = np.isfinite(vg) & np.isfinite(y)
    if valid.sum() < 7:
        return remove

    # 결측만 임시 보간하여 검출에 사용; 최종 데이터에 재삽입하지 않음
    idx = np.arange(n)
    work = y.copy()
    work[~valid] = np.interp(idx[~valid], idx[valid], work[valid])

    kernel_size = max(3, int(kernel_size))
    if kernel_size % 2 == 0:
        kernel_size += 1
    max_kernel = n if n % 2 else n - 1
    kernel_size = min(kernel_size, max_kernel)
    if kernel_size < 3:
        return remove

    # 1차 미분 자체의 국소 spike 검출
    derivative = np.gradient(work, vg)
    d_med = median_filter(derivative, size=kernel_size, mode='nearest')
    d_res = derivative - d_med
    d_sigma = _robust_sigma(d_res)
    derivative_candidate = np.abs(d_res) > z_threshold * d_sigma

    # 원래 current의 점 형태 spike: 양쪽 이웃 연결선 대비 위쪽 돌출량
    expected = work.copy()
    expected[1:-1] = 0.5 * (work[:-2] + work[2:])
    curvature = work - expected
    c_sigma = _robust_sigma(curvature[1:-1])
    point_candidate = curvature > max(0.45 * z_threshold * c_sigma, np.finfo(float).eps)

    # np.gradient 특성상 한 Id spike가 i-1, i, i+1의 derivative에 흔적을 남김.
    # derivative 후보 주변 3점 중 연결선 대비 가장 위로 솟은 실제 Id 점을 제거한다.
    derivative_indices = np.where(derivative_candidate)[0]
    for di in derivative_indices:
        lo = max(1, di - 1)
        hi = min(n - 1, di + 2)
        candidates = np.arange(lo, hi)
        candidates = candidates[point_candidate[candidates]]
        if len(candidates):
            chosen = int(candidates[np.argmax(curvature[candidates])])
            remove[chosen] = True

    # 미분 후보를 놓치더라도 매우 뚜렷한 단일 upward point는 직접 제거
    strong_point = curvature > max(z_threshold * c_sigma, np.finfo(float).eps)
    remove |= strong_point & point_candidate

    # 양 끝점과 비정상 x는 보존/제외
    remove[0] = False
    remove[-1] = False
    remove &= valid
    return remove


def remove_spikes_and_smooth(vg, current):
    """
    반복적으로 derivative spike의 원인이 되는 Id 행을 완전히 삭제한다.
    삭제된 Vg/Id는 plot, Gm, mobility, parameter 계산 어디에도 사용하지 않는다.
    이후 남은 점들끼리만 약한 Savitzky-Golay smoothing을 수행한다.
    """
    vg = np.asarray(vg, dtype=float)
    current = np.asarray(current, dtype=float)
    base_valid = np.isfinite(vg) & np.isfinite(current)

    transformed = np.full(len(current), np.nan, dtype=float)
    signs = np.sign(current)
    signs[signs == 0] = 1.0

    if smooth_log_domain:
        magnitude = np.abs(current)
        nz = magnitude[base_valid & (magnitude > 0)]
        floor = max(np.min(nz) * 0.1, np.finfo(float).tiny) if len(nz) else np.finfo(float).tiny
        transformed[base_valid] = np.log10(np.maximum(magnitude[base_valid], floor))
    else:
        transformed[base_valid] = current[base_valid]

    if clean_full_sweep:
        eligible = base_valid.copy()
    else:
        eligible = base_valid & (np.abs(vg - smooth_center) <= smooth_half_width)

    removed_global = np.zeros(len(current), dtype=bool)
    active_indices = np.where(base_valid)[0]

    # 한 번 제거한 뒤 새로 드러나는 이웃 derivative spike까지 최대 4회 반복 검출
    for _ in range(4):
        if len(active_indices) < 7:
            break
        local_vg = vg[active_indices]
        local_y = transformed[active_indices]
        local_eligible = eligible[active_indices]

        local_remove = detect_derivative_spike_points(
            local_vg, local_y,
            kernel_size=smooth_kernel,
            z_threshold=smooth_z,
        )
        local_remove &= local_eligible
        if not np.any(local_remove):
            break
        removed_global[active_indices[local_remove]] = True
        active_indices = active_indices[~local_remove]

    keep = base_valid & (~removed_global)
    vg_clean = vg[keep]
    y_clean = transformed[keep]
    sign_clean = signs[keep]

    # 남은 점들만 smoothing. 제거점은 절대 보간하거나 plot에 재삽입하지 않음.
    corrected = y_clean.copy()
    n = len(corrected)
    window = int(smooth_window)
    if window % 2 == 0:
        window += 1
    max_window = n if n % 2 else n - 1
    window = min(window, max_window)
    if n >= 5 and window >= 3:
        poly = min(int(smooth_polyorder), window - 1)
        if window > poly:
            corrected = savgol_filter(
                corrected,
                window_length=window,
                polyorder=poly,
                mode='interp',
            )

    if smooth_log_domain:
        current_clean = sign_clean * np.power(10.0, corrected)
    else:
        current_clean = corrected

    return (
        pd.Series(vg_clean).reset_index(drop=True),
        pd.Series(current_clean).reset_index(drop=True),
        removed_global,
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

    if force_auto_peak or master_f not in st.session_state:
        st.session_state[master_f] = float(vg_fwd.iloc[auto_f])
    if force_auto_peak or master_b not in st.session_state:
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

        if force_auto_peak or slider_f not in st.session_state:
            st.session_state[slider_f] = st.session_state[res["master_f"]]
        if force_auto_peak or slider_b not in st.session_state:
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
                "검출된 원래 Id 행은 plot, Gm, mobility 및 parameter 계산에서 완전히 제외되었습니다."
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
