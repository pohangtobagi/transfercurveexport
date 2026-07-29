# FET Analysis Clean UI v4

- Smoothing OFF: 원본 parameter를 큰 카드로 표시
- Smoothing ON:
  - 위쪽 spike 행을 완전히 제거
  - 제거된 점은 plot과 parameter 계산에서 제외
  - 남은 점끼리만 Savitzky–Golay smoothing
  - cleaned mobility curve에서 peak를 새로 자동 탐색
  - 기존 카드 위치에서 mobility, Vth, SS, hysteresis, ON/OFF 값만 교체
- Raw/Smoothed 비교표와 중복 그래프 제거
- ON/OFF current density 단위: A/μm
