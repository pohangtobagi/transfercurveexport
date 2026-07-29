# FET Analysis with Selective Smoothing

## 추가된 기능

- 기본 smoothing 범위: -5 V ~ +5 V
- Forward/Backward sweep를 각각 분리하여 smoothing
- smoothed DrainI로 gm 및 mobility-vs-gate-bias 재계산
- raw/smoothed transfer, gm, mobility 동시 비교
- ON current density = max(|smoothed DrainI|) / Width
- OFF current density = min(nonzero |smoothed DrainI|) / Width
- ON/OFF ratio도 위와 동일한 ON/OFF current 값 사용
- ON/OFF current density 단위: A/μm
- 각 시트 및 전체 평균 결과 지원
- raw/smoothed current, gm, mobility CSV 다운로드

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 주의

Mobility peak는 smoothing 조건에 민감할 수 있습니다. 원본 곡선과 smoothed 곡선을 함께 확인하고,
보정 범위와 window를 분석 기록에 남기는 것을 권장합니다.
