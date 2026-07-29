import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from scipy.signal import savgol_filter
from scipy.ndimage import median_filter

# 1. 페이지 설정
st.set_page_config(page_title="FET-Analysis_Minjae", layout="wide")
st.title("FET-Analysis_Minjae")

# ✅ 드래그바(슬라이더)의 선, 원, 위에 뜨는 숫자까지 모두 검은색/기본색으로 완벽 통일하는 CSS
st.markdown("""
<style>
/* 1. 슬라이더 손잡이(원) 검은색 */
div[data-testid="stSlider"] div[role="slider"] {
    background-color: black !important;
    border-color: black !important;
}
/* 2. 슬라이더 채워진 선(트랙) 검은색으로 강제 덮어쓰기 */
div[data-testid="stSlider"] div[data-testid="stSliderTrack"] > div:nth-child(1) {
    background-color: black !important;
}
/* 3. 슬라이더 위에 뜨는 작은 숫자 말풍선 배경 투명하게, 글씨는 기본색(테마색)으로 */
div[data-testid="stSlider"] div[role="slider"] > div {
    color: var(--text-color) !important;
    background-color: transparent !important;
}
/* 만약 인라인 스타일로 칠해지는 기본 빨간색이 있다면 모두 검은색으로 차단 */
div[data-testid="stSlider"] div[style*="rgb(255, 75, 75)"],
div[data-testid="stSlider"] div[style*="#ff4b4b"] {
    background-color: black !important;
}
</style>
""", unsafe_allow_html=True)

# 2. 소자 파라미터 
st.sidebar.header("Device Information")

# 🌟 Operating Mode 선택 기능 추가 (사이드바 최상단)
operating_mode = st.sidebar.radio("Operating Mode", ["Linear", "Saturation"])
st.sidebar.markdown("---")

W = st.sidebar.number_input("Width (μm)", value=1000, step=50) 
L = st.sidebar.number_input("Length (μm)", value=100, step=50)
Cox_nf = st.sidebar.number_input("Capacitance (nF/cm⁻²)", value=34.5) 
Cox = Cox_nf * 1e-9

st.sidebar.markdown("---")
st.sidebar.header("Smoothing Settings")
apply_smoothing = st.sidebar.checkbox("Remove upward spikes + Apply smoothing", value=False)
smooth_center = st.sidebar.number_input("Center Vg (V)", value=0.0, step=0.5)
smooth_half_width = st.sidebar.number_input("Range (±V)", min_value=0.0, value=5.0, step=0.5)
smooth_kernel = st.sidebar.slider("Spike detection window", 3, 21, 5, 2)
smooth_z = st.sidebar.slider("Upward spike threshold", 2.0, 12.0, 4.0, 0.5, help="작을수록 위로 튀는 점을 더 강하게 제거합니다.")
smooth_use_savgol = st.sidebar.checkbox("Savitzky–Golay smoothing", value=True)
smooth_window = st.sidebar.slider("S-G window", 3, 31, 7, 2)
smooth_polyorder = st.sidebar.slider("S-G polynomial order", 1, 4, 2)
smooth_log_domain = st.sidebar.checkbox("Smooth in log(|Id|) domain", value=True)


def robust_local_spike_mask(y, kernel_size=5, z_threshold=4.0):
    """
    국소 median/MAD 기준으로 '위쪽으로만' 비정상적으로 솟는 spike를 검출.
    아래쪽 dip은 제거하지 않으며, 정상적인 turn-on 곡선은 국소 median과
    양쪽 이웃 추세를 함께 비교해 과도한 단일/소수 점만 제거한다.
    """
    y = np.asarray(y, dtype=float)
    valid = np.isfinite(y)
    result = np.zeros(len(y), dtype=bool)
    if valid.sum() < 5:
        return result

    work = y.copy()
    idx = np.arange(len(y))
    work[~valid] = np.interp(idx[~valid], idx[valid], work[valid])

    kernel_size = max(3, int(kernel_size))
    if kernel_size % 2 == 0:
        kernel_size += 1
    max_kernel = len(work) if len(work) % 2 == 1 else len(work) - 1
    kernel_size = min(kernel_size, max_kernel)
    if kernel_size < 3:
        return result

    local_median = median_filter(work, size=kernel_size, mode="nearest")
    residual = work - local_median

    # 양의 residual만 이용해 robust noise scale 산출
    med = np.median(residual)
    mad = np.median(np.abs(residual - med))
    robust_sigma = 1.4826 * mad
    if not np.isfinite(robust_sigma) or robust_sigma == 0:
        diffs = np.diff(work)
        diff_mad = np.median(np.abs(diffs - np.median(diffs))) if len(diffs) else 0.0
        robust_sigma = max(1.4826 * diff_mad, np.finfo(float).eps)

    candidate = residual > (med + z_threshold * robust_sigma)

    # 양쪽 이웃을 잇는 예상값보다도 확실히 위에 있는 점만 유지
    neighbor_expected = local_median.copy()
    if len(work) >= 3:
        neighbor_expected[1:-1] = 0.5 * (work[:-2] + work[2:])
    neighbor_excess = work - neighbor_expected
    candidate &= neighbor_excess > max(robust_sigma * z_threshold * 0.5, np.finfo(float).eps)

    # sweep 끝점은 peak 판정을 왜곡할 가능성이 커서 자동 제거 대상에서 제외
    candidate[:1] = False
    candidate[-1:] = False
    return candidate & valid


def interpolate_masked_by_index(y, mask):
    """Sweep 순서를 유지한 채 spike 위치를 인접 정상점으로 선형 보간."""
    y = np.asarray(y, dtype=float)
    out = y.copy()
    idx = np.arange(len(y))
    good = np.isfinite(y) & (~mask)
    target = np.isfinite(y) & mask
    if good.sum() >= 2:
        out[target] = np.interp(idx[target], idx[good], y[good])
    return out


def selective_smooth_current(
    vg,
    current,
    center=0.0,
    half_width=5.0,
    median_kernel=5,
    z_threshold=5.0,
    use_savgol=True,
    savgol_window=7,
    savgol_polyorder=2,
    log_domain=True,
):
    """지정 Vg 범위에서만 spike 제거 및 smoothing. 전류 부호는 유지."""
    vg = np.asarray(vg, dtype=float)
    current = np.asarray(current, dtype=float)
    output = current.copy()
    full_spike_mask = np.zeros(len(current), dtype=bool)

    region = np.isfinite(vg) & np.isfinite(current) & (np.abs(vg - center) <= half_width)
    ridx = np.where(region)[0]
    if len(ridx) < 5:
        return output, full_spike_mask

    yr = current[ridx]
    if log_domain:
        sign = np.sign(yr)
        sign[sign == 0] = 1.0
        magnitude = np.abs(yr)
        nz = magnitude[magnitude > 0]
        floor = max(np.nanmin(nz) * 0.1, np.finfo(float).tiny) if len(nz) else np.finfo(float).tiny
        transformed = np.log10(np.maximum(magnitude, floor))
    else:
        sign = np.ones_like(yr)
        transformed = yr.copy()

    local_mask = robust_local_spike_mask(transformed, median_kernel, z_threshold)
    corrected = interpolate_masked_by_index(transformed, local_mask)

    if use_savgol:
        window = int(savgol_window)
        if window % 2 == 0:
            window += 1
        max_window = len(corrected) if len(corrected) % 2 == 1 else len(corrected) - 1
        window = min(window, max_window)
        polyorder = min(int(savgol_polyorder), window - 1)
        if window >= 3 and window > polyorder:
            corrected = savgol_filter(corrected, window_length=window, polyorder=polyorder, mode="interp")

    corrected_current = sign * (10.0 ** corrected) if log_domain else corrected
    output[ridx] = corrected_current
    full_spike_mask[ridx] = local_mask
    return output, full_spike_mask


# 무한대(inf) 값을 0이 아닌 '앞뒤의 정상적인 값'으로 채워 넣는 함수
def fix_inf(gm_array):
    gm_series = pd.Series(gm_array).replace([np.inf, -np.inf], np.nan)
    return gm_series.ffill().bfill().values

# SS 계산 함수 정의
def calculate_ss(id_vals, vg_vals):
    log_id = np.log10(np.abs(id_vals) + 1e-15)
    d_log_id = np.abs(np.gradient(log_id, vg_vals))
    d_log_id_smooth = np.convolve(d_log_id, np.ones(3)/3, mode='same')
    valid_slopes = d_log_id_smooth[np.isfinite(d_log_id_smooth) & (d_log_id_smooth > 0)]
    return (1.0 / np.max(valid_slopes)) * 1000 if len(valid_slopes) > 0 else np.inf

# 큰 글자 카드 UI 함수
def make_card(title, value, color):
    return f"""
    <div style='text-align: left; padding: 5px 0;'>
        <p style='font-size: 20px; margin-bottom: 5px; color: #555;'>{title}</p>
        <p style='font-size: 26px; font-weight: bold; color: {color}; margin: 0; line-height: 1.2;'>{value}</p>
    </div>
    """

# 파라미터 추출 헬퍼 함수 (모드 분기 추가)

def extract_parameters_from_sheet(df, file_id, sheet_name, w, l, cox, mode):
    vg = pd.to_numeric(df['GateV'], errors='coerce').reset_index(drop=True)
    id_original = pd.to_numeric(df['DrainI'], errors='coerce').reset_index(drop=True)
    vd = float(pd.to_numeric(df['DrainV'], errors='coerce').dropna().iloc[0])

    if w <= 0 or l <= 0 or cox <= 0:
        raise ValueError("Width, Length, Capacitance는 모두 0보다 커야 합니다.")
    if mode == "Linear" and abs(vd) == 0:
        raise ValueError("Linear mobility 계산에서는 DrainV가 0이 아니어야 합니다.")

    if abs(vg.max() - vg.iloc[0]) > abs(vg.min() - vg.iloc[0]):
        peak_idx = int(vg.idxmax())
    else:
        peak_idx = int(vg.idxmin())

    vg_fwd = vg.iloc[:peak_idx+1].reset_index(drop=True)
    id_fwd_original = id_original.iloc[:peak_idx+1].reset_index(drop=True)
    vg_bwd = vg.iloc[peak_idx:].reset_index(drop=True)
    id_bwd_original = id_original.iloc[peak_idx:].reset_index(drop=True)

    if apply_smoothing:
        id_fwd_smooth_arr, spike_fwd = selective_smooth_current(
            vg_fwd.values, id_fwd_original.values,
            center=smooth_center, half_width=smooth_half_width,
            median_kernel=smooth_kernel, z_threshold=smooth_z,
            use_savgol=smooth_use_savgol, savgol_window=smooth_window,
            savgol_polyorder=smooth_polyorder, log_domain=smooth_log_domain,
        )
        id_bwd_smooth_arr, spike_bwd = selective_smooth_current(
            vg_bwd.values, id_bwd_original.values,
            center=smooth_center, half_width=smooth_half_width,
            median_kernel=smooth_kernel, z_threshold=smooth_z,
            use_savgol=smooth_use_savgol, savgol_window=smooth_window,
            savgol_polyorder=smooth_polyorder, log_domain=smooth_log_domain,
        )
    else:
        id_fwd_smooth_arr = id_fwd_original.values.copy()
        id_bwd_smooth_arr = id_bwd_original.values.copy()
        spike_fwd = np.zeros(len(id_fwd_original), dtype=bool)
        spike_bwd = np.zeros(len(id_bwd_original), dtype=bool)

    id_fwd_smooth = pd.Series(id_fwd_smooth_arr)
    id_bwd_smooth = pd.Series(id_bwd_smooth_arr)

    def calc_curves(vg_part, id_part):
        vals = np.asarray(id_part, dtype=float)
        if mode == "Linear":
            gm = fix_inf(np.gradient(vals, vg_part.values))
            mobility = (np.abs(gm) * l) / (w * cox * abs(vd))
        else:
            sqrt_id = np.sqrt(np.abs(vals))
            gm = fix_inf(np.gradient(sqrt_id, vg_part.values))
            mobility = (2 * l / (w * cox)) * (gm ** 2)
        return gm, mobility

    gm_fwd_raw, mobility_fwd_raw = calc_curves(vg_fwd, id_fwd_original)
    gm_bwd_raw, mobility_bwd_raw = calc_curves(vg_bwd, id_bwd_original)
    gm_fwd_smooth, mobility_fwd_smooth = calc_curves(vg_fwd, id_fwd_smooth)
    gm_bwd_smooth, mobility_bwd_smooth = calc_curves(vg_bwd, id_bwd_smooth)

    key_fwd = f"val_fwd_{file_id}_{sheet_name}_{mode}"
    key_bwd = f"val_bwd_{file_id}_{sheet_name}_{mode}"

    auto_gm_f = np.abs(gm_fwd_smooth if apply_smoothing else gm_fwd_raw)
    auto_gm_b = np.abs(gm_bwd_smooth if apply_smoothing else gm_bwd_raw)

    if key_fwd in st.session_state:
        target_vg_fwd = st.session_state[key_fwd]
    else:
        idx_f_auto = np.argmax(auto_gm_f[2:-2]) + 2 if len(auto_gm_f) > 5 else np.argmax(auto_gm_f)
        target_vg_fwd = float(vg_fwd.iloc[idx_f_auto])

    if key_bwd in st.session_state:
        target_vg_bwd = st.session_state[key_bwd]
    else:
        idx_b_auto = np.argmax(auto_gm_b[2:-2]) + 2 if len(auto_gm_b) > 5 else np.argmax(auto_gm_b)
        target_vg_bwd = float(vg_bwd.iloc[idx_b_auto])

    vg_pick_fwd = float(vg_fwd.loc[(vg_fwd - target_vg_fwd).abs().idxmin()])
    vg_pick_bwd = float(vg_bwd.loc[(vg_bwd - target_vg_bwd).abs().idxmin()])
    idx_f = int(vg_fwd[vg_fwd == vg_pick_fwd].index[0])
    idx_b = int(vg_bwd[vg_bwd == vg_pick_bwd].index[0])

    def parameter_set(id_fwd, id_bwd, gm_fwd, gm_bwd, mu_fwd_curve, mu_bwd_curve):
        id_fwd = pd.Series(np.asarray(id_fwd, dtype=float))
        id_bwd = pd.Series(np.asarray(id_bwd, dtype=float))

        def safe_vth(id_value, gm_value, vg_value, saturation=False):
            if not np.isfinite(gm_value) or abs(gm_value) <= np.finfo(float).eps:
                return np.nan
            numerator = np.sqrt(abs(id_value)) if saturation else id_value
            return float(-numerator / gm_value + vg_value)

        vth_f = safe_vth(id_fwd.iloc[idx_f], gm_fwd[idx_f], vg_pick_fwd, mode == "Saturation")
        vth_b = safe_vth(id_bwd.iloc[idx_b], gm_bwd[idx_b], vg_pick_bwd, mode == "Saturation")

        full_current = np.concatenate([id_fwd.values, id_bwd.values[1:]])
        finite_abs = np.abs(full_current[np.isfinite(full_current)])
        positive_abs = finite_abs[finite_abs > 0]
        on_current = float(np.max(finite_abs)) if len(finite_abs) else np.nan
        off_current = float(np.min(positive_abs)) if len(positive_abs) else np.nan

        return {
            "mu_fwd": float(mu_fwd_curve[idx_f]),
            "mu_bwd": float(mu_bwd_curve[idx_b]),
            "vth_fwd": vth_f,
            "vth_bwd": vth_b,
            "gm_max_fwd": vg_pick_fwd,
            "gm_max_bwd": vg_pick_bwd,
            "ss_fwd": calculate_ss(id_fwd.values, vg_fwd.values),
            "ss_bwd": calculate_ss(id_bwd.values, vg_bwd.values),
            "hysteresis": abs(vth_f - vth_b) if np.isfinite(vth_f) and np.isfinite(vth_b) else np.nan,
            "on_current": on_current,
            "off_current": off_current,
            "onoff": on_current / off_current if np.isfinite(off_current) and off_current > 0 else np.nan,
            "on_current_density": on_current / w if np.isfinite(on_current) else np.nan,
            "off_current_density": off_current / w if np.isfinite(off_current) else np.nan,
        }

    raw_params = parameter_set(
        id_fwd_original, id_bwd_original,
        gm_fwd_raw, gm_bwd_raw,
        mobility_fwd_raw, mobility_bwd_raw,
    )
    smooth_params = parameter_set(
        id_fwd_smooth, id_bwd_smooth,
        gm_fwd_smooth, gm_bwd_smooth,
        mobility_fwd_smooth, mobility_bwd_smooth,
    )

    return {
        "raw": raw_params,
        "smooth": smooth_params,
        "vg_fwd": vg_fwd,
        "vg_bwd": vg_bwd,
        "id_fwd_original": id_fwd_original,
        "id_bwd_original": id_bwd_original,
        "id_fwd_smooth": id_fwd_smooth,
        "id_bwd_smooth": id_bwd_smooth,
        "gm_fwd_raw": gm_fwd_raw,
        "gm_bwd_raw": gm_bwd_raw,
        "gm_fwd_smooth": gm_fwd_smooth,
        "gm_bwd_smooth": gm_bwd_smooth,
        "mobility_fwd_raw": mobility_fwd_raw,
        "mobility_bwd_raw": mobility_bwd_raw,
        "mobility_fwd_smooth": mobility_fwd_smooth,
        "mobility_bwd_smooth": mobility_bwd_smooth,
        "spike_fwd": spike_fwd,
        "spike_bwd": spike_bwd,
        "vg_full": vg,
        "vd": vd,
    }


def sci(value, digits=2):
    if not np.isfinite(value) or value <= 0:
        return "N/A"
    exp = int(np.floor(np.log10(value)))
    coef = value / (10 ** exp)
    return f"{coef:.{digits}f}E{exp}"


def parameter_table(raw, smooth=None):
    rows = [
        ("Forward peak mobility (cm²/V·s)", raw["mu_fwd"], smooth["mu_fwd"] if smooth else None),
        ("Forward Vth (V)", raw["vth_fwd"], smooth["vth_fwd"] if smooth else None),
        ("Forward SS (mV/dec)", raw["ss_fwd"], smooth["ss_fwd"] if smooth else None),
        ("Backward peak mobility (cm²/V·s)", raw["mu_bwd"], smooth["mu_bwd"] if smooth else None),
        ("Backward Vth (V)", raw["vth_bwd"], smooth["vth_bwd"] if smooth else None),
        ("Backward SS (mV/dec)", raw["ss_bwd"], smooth["ss_bwd"] if smooth else None),
        ("Hysteresis (V)", raw["hysteresis"], smooth["hysteresis"] if smooth else None),
        ("ON/OFF ratio", raw["onoff"], smooth["onoff"] if smooth else None),
        ("ON current / Width (A/μm)", raw["on_current_density"], smooth["on_current_density"] if smooth else None),
        ("OFF current / Width (A/μm)", raw["off_current_density"], smooth["off_current_density"] if smooth else None),
    ]
    data = {"Parameter": [r[0] for r in rows], "Raw": [r[1] for r in rows]}
    if smooth is not None:
        data["After spike removal + smoothing"] = [r[2] for r in rows]
        data["Change"] = [
            (r[2] - r[1]) if np.isfinite(r[1]) and np.isfinite(r[2]) else np.nan
            for r in rows
        ]
    return pd.DataFrame(data)

# 3. 파일 업로드
uploaded_file = st.file_uploader("측정된 엑셀 파일을 업로드하세요", type=["xlsx", "xls"])

if uploaded_file:
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    
    xls = pd.ExcelFile(uploaded_file)
    sheet_names = xls.sheet_names
    target_sheets = [s for s in sheet_names if s == 'Data' or s.lower().startswith('append')]
    
    if not target_sheets:
        st.error("분석할 수 있는 시트('Data' 또는 'Append...')가 없습니다.")
    else:
        # 최초 1회 세션 초기화 로직
        for s_name in target_sheets:
            key_f_init = f"val_fwd_{file_id}_{s_name}_{operating_mode}"
            key_b_init = f"val_bwd_{file_id}_{s_name}_{operating_mode}"
            
            if key_f_init not in st.session_state:
                temp_df = pd.read_excel(uploaded_file, sheet_name=s_name)
                temp_vg = temp_df['GateV']
                temp_id = temp_df['DrainI']
                if abs(temp_vg.max() - temp_vg.iloc[0]) > abs(temp_vg.min() - temp_vg.iloc[0]):
                    p_idx = temp_vg.idxmax()
                else: p_idx = temp_vg.idxmin()
                temp_fwd_vg, temp_fwd_id = temp_vg[:p_idx+1].reset_index(drop=True), temp_id[:p_idx+1].reset_index(drop=True)
                temp_bwd_vg, temp_bwd_id = temp_vg[p_idx:].reset_index(drop=True), temp_id[p_idx:].reset_index(drop=True)
                
                if operating_mode == "Linear":
                    gm_f_init = np.abs(fix_inf(np.gradient(temp_fwd_id.values, temp_fwd_vg.values)))
                    gm_b_init = np.abs(fix_inf(np.gradient(temp_bwd_id.values, temp_bwd_vg.values)))
                else:
                    gm_f_init = np.abs(fix_inf(np.gradient(np.sqrt(np.abs(temp_fwd_id.values)), temp_fwd_vg.values)))
                    gm_b_init = np.abs(fix_inf(np.gradient(np.sqrt(np.abs(temp_bwd_id.values)), temp_bwd_vg.values)))
                
                idx_f_init = np.argmax(gm_f_init[2:-2]) + 2 if len(gm_f_init) > 5 else np.argmax(gm_f_init)
                idx_b_init = np.argmax(gm_b_init[2:-2]) + 2 if len(gm_b_init) > 5 else np.argmax(gm_b_init)
                
                st.session_state[key_f_init] = float(temp_fwd_vg.iloc[idx_f_init])
                st.session_state[key_b_init] = float(temp_bwd_vg.iloc[idx_b_init])

        st.sidebar.markdown("---")
        options = target_sheets + ["Average (All Sheets)"]
        selected_sheet = st.sidebar.selectbox("📂 Select Data Sheet", options)
        
        # =====================================================================
        # [모드 1] Average (All Sheets) 선택 시 로직
        # =====================================================================
        if selected_sheet == "Average (All Sheets)":
            st.markdown(f"<h3 style='color: #333;'>📊 Statistics ({operating_mode} - Average of {len(target_sheets)} sheets)</h3>", unsafe_allow_html=True)

            rows = []
            for sheet in target_sheets:
                df = pd.read_excel(uploaded_file, sheet_name=sheet)
                if 'GateV' in df.columns and 'DrainI' in df.columns:
                    res_sheet = extract_parameters_from_sheet(df, file_id, sheet, W, L, Cox, operating_mode)
                    row = {"sheet": sheet}
                    row.update({f"raw_{k}": v for k, v in res_sheet["raw"].items()})
                    row.update({f"smooth_{k}": v for k, v in res_sheet["smooth"].items()})
                    row["removed_spikes"] = int(np.sum(res_sheet["spike_fwd"]) + np.sum(res_sheet["spike_bwd"]))
                    rows.append(row)

            if not rows:
                st.error("유효한 데이터가 있는 시트가 없습니다.")
            else:
                stat_df = pd.DataFrame(rows)
                keys = [
                    ("mu_fwd", "Forward peak mobility"),
                    ("vth_fwd", "Forward Vth"),
                    ("ss_fwd", "Forward SS"),
                    ("mu_bwd", "Backward peak mobility"),
                    ("vth_bwd", "Backward Vth"),
                    ("ss_bwd", "Backward SS"),
                    ("hysteresis", "Hysteresis"),
                    ("onoff", "ON/OFF ratio"),
                    ("on_current_density", "ON current / Width (A/μm)"),
                    ("off_current_density", "OFF current / Width (A/μm)"),
                ]
                summary = []
                for key, label in keys:
                    item = {
                        "Parameter": label,
                        "Raw mean": stat_df[f"raw_{key}"].mean(),
                        "Raw std": stat_df[f"raw_{key}"].std(),
                    }
                    if apply_smoothing:
                        item["Smoothed mean"] = stat_df[f"smooth_{key}"].mean()
                        item["Smoothed std"] = stat_df[f"smooth_{key}"].std()
                    summary.append(item)

                st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
                if apply_smoothing:
                    st.success(f"전체 시트에서 upward spike 총 {int(stat_df['removed_spikes'].sum())}개 제거 후 모든 parameter를 재계산했습니다.")
                else:
                    st.info("Smoothing을 체크하면 Raw 평균과 Smoothed 평균이 함께 표시됩니다.")
                st.markdown("---")

        # =====================================================================
        # [모드 2] 특정 단일 시트 선택 시 로직
        # =====================================================================
        else:
            df = pd.read_excel(uploaded_file, sheet_name=selected_sheet)
            if 'GateV' not in df.columns or 'DrainI' not in df.columns:
                st.warning(f"'{selected_sheet}' 시트에 'GateV' 또는 'DrainI' 컬럼이 없어 분석할 수 없습니다.")
            else:
                # ✅ 함수 호출 결과 받기
                res = extract_parameters_from_sheet(df, file_id, selected_sheet, W, L, Cox, operating_mode)
                
                vg_fwd, vg_bwd = res['vg_fwd'], res['vg_bwd']
                id_fwd, id_bwd = res['id_fwd_smooth'], res['id_bwd_smooth']
                id_fwd_original, id_bwd_original = res['id_fwd_original'], res['id_bwd_original']
                gm_fwd_raw, gm_fwd_smooth = res['gm_fwd_raw'], res['gm_fwd_smooth']
                gm_bwd_raw, gm_bwd_smooth = res['gm_bwd_raw'], res['gm_bwd_smooth']
                mobility_fwd_raw, mobility_fwd_smooth = res['mobility_fwd_raw'], res['mobility_fwd_smooth']
                mobility_bwd_raw, mobility_bwd_smooth = res['mobility_bwd_raw'], res['mobility_bwd_smooth']
                vg = res['vg_full']
                vd_val = res['vd'] 
                
                has_ig = 'GateI' in df.columns
                if has_ig:
                    ig_raw = df['GateI']
                    peak_idx = len(vg_fwd) - 1
                    ig_fwd, ig_bwd = ig_raw[:peak_idx+1].reset_index(drop=True), ig_raw[peak_idx:].reset_index(drop=True)

                st.sidebar.markdown("---")
                st.sidebar.markdown(f"**Peak Point Adjustment ({selected_sheet})**")
                vg_step = float(abs(vg_fwd.iloc[1] - vg_fwd.iloc[0])) if len(vg_fwd) > 1 else 0.5
                
                # 마스터 세션 키
                key_f_current = f"val_fwd_{file_id}_{selected_sheet}_{operating_mode}"
                key_b_current = f"val_bwd_{file_id}_{selected_sheet}_{operating_mode}"
                
                # 위젯 고유 키
                fwd_slider_key = f"fs_{file_id}_{selected_sheet}_{operating_mode}"
                fwd_number_key = f"fn_{file_id}_{selected_sheet}_{operating_mode}"
                bwd_slider_key = f"bs_{file_id}_{selected_sheet}_{operating_mode}"
                bwd_number_key = f"bn_{file_id}_{selected_sheet}_{operating_mode}"

                # 가장 확실한 연동 방식: 위젯이 그려지기 전에 세션 키를 서로 동기화
                if fwd_slider_key not in st.session_state:
                    st.session_state[fwd_slider_key] = st.session_state[key_f_current]
                if fwd_number_key not in st.session_state:
                    st.session_state[fwd_number_key] = st.session_state[key_f_current]
                if bwd_slider_key not in st.session_state:
                    st.session_state[bwd_slider_key] = st.session_state[key_b_current]
                if bwd_number_key not in st.session_state:
                    st.session_state[bwd_number_key] = st.session_state[key_b_current]

                # 콜백 함수: 하나가 바뀌면 다른 위젯 키와 마스터 키를 모두 업데이트
                def sync_fwd_from_slider():
                    val = st.session_state[fwd_slider_key]
                    st.session_state[fwd_number_key] = val
                    st.session_state[key_f_current] = val

                def sync_fwd_from_number():
                    val = st.session_state[fwd_number_key]
                    st.session_state[fwd_slider_key] = val
                    st.session_state[key_f_current] = val

                def sync_bwd_from_slider():
                    val = st.session_state[bwd_slider_key]
                    st.session_state[bwd_number_key] = val
                    st.session_state[key_b_current] = val

                def sync_bwd_from_number():
                    val = st.session_state[bwd_number_key]
                    st.session_state[bwd_slider_key] = val
                    st.session_state[key_b_current] = val

                # 🌟 Forward UI
                st.sidebar.markdown("<span style=' font-weight: bold;'>Forward $V_g$ Point</span>", unsafe_allow_html=True)
                fwd_min, fwd_max = float(vg_fwd.min()), float(vg_fwd.max())
                
                # 주의: value 인자를 제거하고 오직 key로만 제어
                st.sidebar.slider(
                    "Fwd Vg Drag", 
                    min_value=fwd_min, max_value=fwd_max, 
                    step=vg_step, 
                    key=fwd_slider_key,
                    on_change=sync_fwd_from_slider,
                    label_visibility="collapsed"
                )
                
                st.sidebar.number_input(
                    "Fwd Vg Button", 
                    min_value=fwd_min, max_value=fwd_max, 
                    step=vg_step, format="%.2f", 
                    key=fwd_number_key,
                    on_change=sync_fwd_from_number,
                    label_visibility="collapsed"
                )
                
                # 🌟 Backward UI
                st.sidebar.markdown("<br><span style=' font-weight: bold;'>Backward $V_g$ Point</span>", unsafe_allow_html=True)
                bwd_min, bwd_max = float(vg_bwd.min()), float(vg_bwd.max())
                
                st.sidebar.slider(
                    "Bwd Vg Drag", 
                    min_value=bwd_min, max_value=bwd_max, 
                    step=vg_step, 
                    key=bwd_slider_key,
                    on_change=sync_bwd_from_slider,
                    label_visibility="collapsed"
                )
                
                st.sidebar.number_input(
                    "Bwd Vg Button", 
                    min_value=bwd_min, max_value=bwd_max, 
                    step=vg_step, format="%.2f", 
                    key=bwd_number_key,
                    on_change=sync_bwd_from_number,
                    label_visibility="collapsed"
                )

                # UI 출력값 구성
                raw_p = res["raw"]
                smooth_p = res["smooth"]
                active_p = smooth_p if apply_smoothing else raw_p
                vg_max_gm_fwd = active_p["gm_max_fwd"]
                vg_max_gm_bwd = active_p["gm_max_bwd"]

                st.markdown(f"<h3 style='color: #333;'>📊 Data Sheet: {selected_sheet} ({operating_mode} Mode)</h3>", unsafe_allow_html=True)

                st.markdown("<h4>Raw Parameters</h4>", unsafe_allow_html=True)
                st.dataframe(parameter_table(raw_p), use_container_width=True, hide_index=True)

                if apply_smoothing:
                    removed_total = int(np.sum(res["spike_fwd"]) + np.sum(res["spike_bwd"]))
                    st.success(
                        f"Upward spike {removed_total}개를 제거한 뒤 smoothing을 적용했습니다. "
                        "아래 값은 보정된 DrainI로 gm, mobility, Vth, SS, hysteresis, ON/OFF를 모두 다시 계산한 결과입니다."
                    )
                    st.markdown("<h4 style='color:#2E60AB;'>Raw vs Smoothed Parameters</h4>", unsafe_allow_html=True)
                    st.dataframe(parameter_table(raw_p, smooth_p), use_container_width=True, hide_index=True)

                    st.markdown("<h4 style='color:#6FADCF;'>Forward Sweep — Smoothed</h4>", unsafe_allow_html=True)
                    f1, f2, f3, f4 = st.columns(4)
                    f1.markdown(make_card("Peak Mobility", f"{smooth_p['mu_fwd']:.2f} cm²/V·s", "#2E60AB"), unsafe_allow_html=True)
                    f2.markdown(make_card("Threshold Voltage (Vₜₕ)", f"{smooth_p['vth_fwd']:.2f} V", "#A23B72"), unsafe_allow_html=True)
                    f3.markdown(make_card("Peak Point (Vg)", f"{smooth_p['gm_max_fwd']:.1f} V", "#F18F01"), unsafe_allow_html=True)
                    f4.markdown(make_card("SS", f"{smooth_p['ss_fwd']:.1f} mV/dec", "#18A558"), unsafe_allow_html=True)

                    st.markdown("<h4 style='color:#F05650;'>Backward Sweep — Smoothed</h4>", unsafe_allow_html=True)
                    b1, b2, b3, b4 = st.columns(4)
                    b1.markdown(make_card("Peak Mobility", f"{smooth_p['mu_bwd']:.2f} cm²/V·s", "#2E60AB"), unsafe_allow_html=True)
                    b2.markdown(make_card("Threshold Voltage (Vₜₕ)", f"{smooth_p['vth_bwd']:.2f} V", "#A23B72"), unsafe_allow_html=True)
                    b3.markdown(make_card("Peak Point (Vg)", f"{smooth_p['gm_max_bwd']:.1f} V", "#F18F01"), unsafe_allow_html=True)
                    b4.markdown(make_card("SS", f"{smooth_p['ss_bwd']:.1f} mV/dec", "#18A558"), unsafe_allow_html=True)

                    st.markdown("<h4>Overall — Smoothed</h4>", unsafe_allow_html=True)
                    o1, o2, o3, o4 = st.columns(4)
                    o1.markdown(make_card("On/Off Ratio", sci(smooth_p["onoff"]), "#5B5F97"), unsafe_allow_html=True)
                    o2.markdown(make_card("ON Current / Width", f"{smooth_p['on_current_density']:.3E} A/μm", "#5B5F97"), unsafe_allow_html=True)
                    o3.markdown(make_card("OFF Current / Width", f"{smooth_p['off_current_density']:.3E} A/μm", "#5B5F97"), unsafe_allow_html=True)
                    o4.markdown(make_card("Hysteresis", f"{smooth_p['hysteresis']:.2f} V", "#5B5F97"), unsafe_allow_html=True)
                else:
                    st.info("Smoothing 체크박스를 켜면 upward spike 제거 후 재계산된 parameter가 Raw 값과 함께 표시됩니다.")

                st.markdown("---")

                # 그래프 생성 (모드에 따라 타이틀 분기)
                graph3_title = "3. Transconductance (Gₘ)" if operating_mode == "Linear" else "3. d(√I<sub>D</sub>)/dV<sub>G</sub>"
                # ✅ 4번 그래프 Y축 이름 분기
                graph4_title = "4. Linear Mobility" if operating_mode == "Linear" else "4. Saturation Mobility"

                fig = make_subplots(rows=2, cols=2, 
                                    subplot_titles=("1. Transfer (Log Scale)", "2. Transfer (Linear Scale)", 
                                                    graph3_title, graph4_title),
                                    horizontal_spacing=0.25, vertical_spacing=0.25)

                color_fwd, color_bwd = 'blue', 'red'
                color_fwd_smooth, color_bwd_smooth = '#6FADCF', '#F05650'
                dense_dash = '5px, 4px'

                fig.add_trace(go.Scatter(x=vg_fwd, y=id_fwd_original.abs(), name="Forward raw", line=dict(color=color_fwd, width=1, dash='dot'), opacity=0.45, legend="legend"), row=1, col=1)
                fig.add_trace(go.Scatter(x=vg_bwd, y=id_bwd_original.abs(), name="Backward raw", line=dict(color=color_bwd, width=1, dash='dot'), opacity=0.45, legend="legend"), row=1, col=1)
                fig.add_trace(go.Scatter(x=vg_fwd, y=id_fwd.abs(), name="Forward corrected", line=dict(color=color_fwd_smooth, width=2.5), legend="legend"), row=1, col=1)
                fig.add_trace(go.Scatter(x=vg_bwd, y=id_bwd.abs(), name="Backward corrected", line=dict(color=color_bwd_smooth, width=2.5), legend="legend"), row=1, col=1)
                if apply_smoothing and np.any(res["spike_fwd"]):
                    fig.add_trace(go.Scatter(
                        x=vg_fwd[res["spike_fwd"]],
                        y=id_fwd_original.abs()[res["spike_fwd"]],
                        mode="markers", name="Removed Fwd spikes",
                        marker=dict(symbol="x", size=10, color="black"),
                        legend="legend"
                    ), row=1, col=1)
                if apply_smoothing and np.any(res["spike_bwd"]):
                    fig.add_trace(go.Scatter(
                        x=vg_bwd[res["spike_bwd"]],
                        y=id_bwd_original.abs()[res["spike_bwd"]],
                        mode="markers", name="Removed Bwd spikes",
                        marker=dict(symbol="x", size=10, color="black"),
                        legend="legend"
                    ), row=1, col=1)

                if has_ig:
                    fig.add_trace(go.Scatter(x=vg_fwd, y=ig_fwd.abs(), name="Ig (Fwd)", line=dict(color='dimgray', dash='dot'), showlegend=False), row=1, col=1)
                    fig.add_trace(go.Scatter(x=vg_bwd, y=ig_bwd.abs(), name="Ig (Bwd)", line=dict(color='dimgray', dash='dot'), showlegend=False), row=1, col=1)
                    
                fig.add_trace(go.Scatter(x=vg_fwd, y=id_fwd_original.abs(), name="Forward raw", line=dict(color=color_fwd, width=1, dash='dot'), opacity=0.45, legend="legend2"), row=1, col=2)
                fig.add_trace(go.Scatter(x=vg_bwd, y=id_bwd_original.abs(), name="Backward raw", line=dict(color=color_bwd, width=1, dash='dot'), opacity=0.45, legend="legend2"), row=1, col=2)
                fig.add_trace(go.Scatter(x=vg_fwd, y=id_fwd.abs(), name="Forward corrected", line=dict(color=color_fwd_smooth, width=2.5), legend="legend2"), row=1, col=2)
                fig.add_trace(go.Scatter(x=vg_bwd, y=id_bwd.abs(), name="Backward corrected", line=dict(color=color_bwd_smooth, width=2.5), legend="legend2"), row=1, col=2)
                        
                fig.add_trace(go.Scatter(x=vg_fwd, y=np.abs(gm_fwd_raw), name="Forward raw", line=dict(color=color_fwd, width=1, dash='dot'), opacity=0.45, legend="legend3"), row=2, col=1)
                fig.add_trace(go.Scatter(x=vg_bwd, y=np.abs(gm_bwd_raw), name="Backward raw", line=dict(color=color_bwd, width=1, dash='dot'), opacity=0.45, legend="legend3"), row=2, col=1)
                fig.add_trace(go.Scatter(x=vg_fwd, y=np.abs(gm_fwd_smooth), name="Forward corrected", line=dict(color=color_fwd_smooth, width=2.5), legend="legend3"), row=2, col=1)
                fig.add_trace(go.Scatter(x=vg_bwd, y=np.abs(gm_bwd_smooth), name="Backward corrected", line=dict(color=color_bwd_smooth, width=2.5), legend="legend3"), row=2, col=1)
                
                # 시각화 
                fig.add_vline(x=vg_max_gm_fwd, line_width=1.5, line_dash=dense_dash, line_color=color_fwd_smooth, opacity=0.8, row=2, col=1)
                fig.add_vline(x=vg_max_gm_bwd, line_width=1.5, line_dash=dense_dash, line_color=color_bwd_smooth, opacity=0.8, row=2, col=1)
                        
                fig.add_trace(go.Scatter(x=vg_fwd, y=mobility_fwd_raw, name="Forward raw", line=dict(color=color_fwd, width=1, dash='dot'), opacity=0.45, legend="legend4"), row=2, col=2)
                fig.add_trace(go.Scatter(x=vg_bwd, y=mobility_bwd_raw, name="Backward raw", line=dict(color=color_bwd, width=1, dash='dot'), opacity=0.45, legend="legend4"), row=2, col=2)
                fig.add_trace(go.Scatter(x=vg_fwd, y=mobility_fwd_smooth, name="Forward corrected", line=dict(color=color_fwd_smooth, width=2.5), legend="legend4"), row=2, col=2)
                fig.add_trace(go.Scatter(x=vg_bwd, y=mobility_bwd_smooth, name="Backward corrected", line=dict(color=color_bwd_smooth, width=2.5), legend="legend4"), row=2, col=2)
                
                fig.add_vline(x=vg_max_gm_fwd, line_width=1.5, line_dash=dense_dash, line_color=color_fwd_smooth, opacity=0.8, row=2, col=2)
                fig.add_vline(x=vg_max_gm_bwd, line_width=1.5, line_dash=dense_dash, line_color=color_bwd_smooth, opacity=0.8, row=2, col=2)
                
                # ✅ 1번 그래프 좌하단에 DrainV 표시 추가 및 글씨 줄임 (유효숫자 처리)
                vd_formatted = f"{vd_val:.2f}".rstrip('0').rstrip('.') # 불필요한 0과 소수점 제거 (예: -0.1000 -> -0.1)
                fig.add_annotation(
                    x=0.001, y=0.001, xref="x domain", yref="y domain",
                    text=f"<b>V<sub>D</sub> = {vd_formatted} V</b>",
                    showarrow=False,
                    font=dict(size=12, color="black"),
                    row=1, col=1
                )

                # ✅ Legend 폰트 크기 증가
                leg_style = dict(bgcolor="rgba(255,255,255,0.8)", bordercolor="black", borderwidth=1, xanchor="right", yanchor="top", font=dict(color="black", size=14))

                # ✅ Subplot 타이틀 폰트 크기 증가 (Drain V 크기 인듯 ?)
                fig.update_annotations(font_size=16)

                fig.update_layout(width=1000, height=1000, autosize=False, template="plotly_white", margin=dict(t=120, b=80, l=100, r=100),
                                  legend=dict(x=0.375, y=1.0, **leg_style), legend2=dict(x=1.0, y=1.0, **leg_style),
                                  legend3=dict(x=0.375, y=0.375, **leg_style), legend4=dict(x=1.0, y=0.375, **leg_style))
                
                # ✅ 에러 방지 처리 (AttributeError: 'Annotation' object has no attribute 'get')
                # getattr 또는 hasattr을 사용하여 안전하게 접근
                for annotation in fig['layout']['annotations']:
                    ann_text = getattr(annotation, 'text', '')
                    if ann_text is not None and 'V<sub>D</sub>' not in str(ann_text):
                        annotation.font.color = 'black'
                        annotation.font.size = 22
                        annotation.yshift = 25
                
                # ✅ X축, Y축 라벨 폰트 크기 및 눈금 폰트 크기 증가
                common_axis_params = dict(
                    ticks="outside", tickwidth=1.5, tickcolor='black', ticklen=8, 
                    showline=True, linewidth=1.5, linecolor='black', mirror=True, 
                    showgrid=True, gridwidth=1, gridcolor='lightgray', griddash='dot', 
                    zeroline=False, layer='below traces',
                    title_font=dict(size=22),
                    tickfont=dict(size=15)
                )

                # ✅ NameError 해결 (원본 데이터 추출 함수에서 넘겨받은 vg_full 활용)
                vg_range = abs(vg.max() - vg.min())
                dynamic_dtick = 2.5 if vg_range <= 10 else 10

                y_title_3 = "Gₘ (S)" if operating_mode == "Linear" else "d(√I<sub>D</sub>)/dV<sub>G</sub> (A<sup>0.5</sup>/V)"
                # ✅ Y축 타이틀 분기
                y_title_4 = "Linear Mobility (cm²/V·s)" if operating_mode == "Linear" else "Saturation Mobility (cm²/V·s)"

                fig.update_xaxes(title_text="Gate Voltage (V)", dtick=dynamic_dtick, **common_axis_params)
                fig.update_yaxes(**common_axis_params)
                fig.update_yaxes(title_text="Drain Current (A)", type="log", dtick=1, exponentformat="power", row=1, col=1)
                fig.update_yaxes(title_text="Drain Current (A)", exponentformat="power", row=1, col=2)
                fig.update_yaxes(title_text=y_title_3, exponentformat="power", row=2, col=1)
                fig.update_yaxes(title_text=y_title_4, row=2, col=2)

                st.plotly_chart(fig, use_container_width=False)

                # 분석 결과 및 smoothed curve 다운로드
                export_df = pd.DataFrame({
                    "GateV_forward": vg_fwd,
                    "DrainI_forward_raw": id_fwd_original,
                    "DrainI_forward_smoothed": id_fwd,
                    "gm_forward_raw": gm_fwd_raw,
                    "gm_forward_smoothed": gm_fwd_smooth,
                    "mobility_forward_raw": mobility_fwd_raw,
                    "mobility_forward_smoothed": mobility_fwd_smooth,
                    "upward_spike_removed_forward": res["spike_fwd"],
                })
                bwd_export = pd.DataFrame({
                    "GateV_backward": vg_bwd,
                    "DrainI_backward_raw": id_bwd_original,
                    "DrainI_backward_smoothed": id_bwd,
                    "gm_backward_raw": gm_bwd_raw,
                    "gm_backward_smoothed": gm_bwd_smooth,
                    "mobility_backward_raw": mobility_bwd_raw,
                    "mobility_backward_smoothed": mobility_bwd_smooth,
                    "upward_spike_removed_backward": res["spike_bwd"],
                })
                export_df = pd.concat([export_df, bwd_export], axis=1)
                st.download_button(
                    "Download smoothed current & mobility (CSV)",
                    data=export_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{selected_sheet}_{operating_mode}_smoothed_analysis.csv",
                    mime="text/csv",
                )
