from typing import Optional

SIGNIFICANT_THRESHOLDS: dict[str, float] = {
    "egfr": 10.0,        # mL/min/1.73m² — 신장 기능
    "creatinine": 0.3,   # mg/dL
    "hba1c": 0.5,        # %
    "potassium": 0.5,    # mEq/L — 고칼륨혈증 위험
    "ldl": 20.0,         # mg/dL
    "bnp": 100.0,        # pg/mL — 심부전
    "nt_probnp": 300.0,  # pg/mL
}

DISPLAY_NAMES: dict[str, str] = {
    "egfr": "eGFR(mL/min)",
    "creatinine": "Creatinine(mg/dL)",
    "hba1c": "HbA1c(%)",
    "potassium": "K+(mEq/L)",
    "ldl": "LDL(mg/dL)",
    "bnp": "BNP(pg/mL)",
    "nt_probnp": "NT-proBNP(pg/mL)",
}


def compute_deltas(snapshots: list[dict]) -> list[dict]:
    """
    snapshots: 최신순 정렬된 [{recorded_at, lab_values}, ...] 리스트
    반환: 인접 시점 간 delta 목록 (인덱스 0 = 가장 최근 변화)
    """
    if len(snapshots) < 2:
        return []

    result = []
    for i in range(len(snapshots) - 1):
        current = snapshots[i]["lab_values"]
        previous = snapshots[i + 1]["lab_values"]
        entry: dict = {
            "from_date": snapshots[i + 1]["recorded_at"],
            "to_date": snapshots[i]["recorded_at"],
            "deltas": {},
        }
        for key, threshold in SIGNIFICANT_THRESHOLDS.items():
            curr_val = current.get(key)
            prev_val = previous.get(key)
            if curr_val is not None and prev_val is not None:
                delta = curr_val - prev_val
                entry["deltas"][key] = {
                    "from": prev_val,
                    "to": curr_val,
                    "delta": round(delta, 2),
                    "significant": abs(delta) >= threshold,
                    "direction": "up" if delta > 0 else "down",
                }
        result.append(entry)
    return result


def format_delta_for_prompt(
    snapshots: list[dict],
    current_lab: Optional[dict] = None,
) -> str:
    """
    Lab 시계열을 LLM 프롬프트용 텍스트 표로 변환.
    snapshots: 최신순 정렬된 DB 기록
    current_lab: 이번 진료에서 입력된 최신 수치 (있으면 맨 앞에 삽입)
    """
    all_snaps: list[dict] = list(snapshots)
    if current_lab:
        all_snaps = [{"recorded_at": "현재", "lab_values": current_lab}] + all_snaps

    if not all_snaps:
        return "Lab 수치 이력 없음"

    keys = [
        k for k in SIGNIFICANT_THRESHOLDS
        if any(s["lab_values"].get(k) is not None for s in all_snaps)
    ]
    if not keys:
        return "유효한 Lab 수치 없음"

    headers = [
        str(s["recorded_at"])[:10] if s["recorded_at"] != "현재" else "현재"
        for s in reversed(all_snaps)
    ]
    lines = [f"| 항목 | {' | '.join(headers)} | 총변화 |"]
    lines.append("|" + "---|" * (len(all_snaps) + 2))

    for key in keys:
        vals = [s["lab_values"].get(key) for s in reversed(all_snaps)]
        non_none = [v for v in vals if v is not None]
        if len(non_none) < 2:
            continue
        total_delta = non_none[-1] - non_none[0]
        threshold = SIGNIFICANT_THRESHOLDS[key]
        if abs(total_delta) >= threshold * 2:
            flag = " ⚠️급격"
        elif abs(total_delta) >= threshold:
            flag = " ↑" if total_delta > 0 else " ↓"
        else:
            flag = ""
        val_strs = [str(v) if v is not None else "-" for v in vals]
        name = DISPLAY_NAMES.get(key, key)
        lines.append(f"| {name} | {' | '.join(val_strs)} | {total_delta:+.1f}{flag} |")

    return "\n".join(lines)
