"""Deterministic Vietnamese presentation assessment for planner results.

This module interprets existing metrics for UX only.  It must not participate
in geometry calculation, subset ranking, reception eligibility, or quality
classification.
"""
import math
import statistics

from .coverage import ground_distance_km


UX_THRESHOLDS = {
    "reception_percent": [90, 75, 50, 25],
    "geometry_good_percent": [75, 50, 25, 10],
    "branch_good_percent": [90, 75, 50, 25],
    "n_minus_1_percent": [80, 60, 30, 10],
    "redundancy_percent": [80, 60, 30, 10],
    "p95_m": {
        "rat_tot": {"median_max": 250, "p90_max": 500},
        "tot": {"median_max": 500, "p90_max": 1500},
        "trung_binh": {"median_max": 1500, "p90_max": 5000},
        "kem": {"median_max": 5000},
    },
    "dependency_min_samples": 3,
}

LEVELS = {
    "RAT_TOT": ("Rất tốt", 4),
    "TOT": ("Tốt", 3),
    "TRUNG_BINH": ("Trung bình", 2),
    "KEM": ("Kém", 1),
    "RAT_KEM": ("Rất kém", 0),
    "KHONG_AP_DUNG": ("Không áp dụng", None),
    "KHONG_DU_DU_LIEU": ("Chưa đủ dữ liệu", None),
}

OVERALL = {
    4: ("RAT_TOT", "Rất tốt"),
    3: ("TOT", "Tốt"),
    2: ("KHA", "Khá"),
    1: ("TRUNG_BINH", "Trung bình"),
    0: ("KEM", "Kém"),
}


def _number_vi(value, digits=1):
    if value is None or not math.isfinite(float(value)):
        return "—"
    text = f"{float(value):.{digits}f}"
    return text.replace(".", ",")


def _percent_level(value, thresholds):
    if value is None:
        return "KHONG_DU_DU_LIEU"
    for code, threshold in zip(
            ("RAT_TOT", "TOT", "TRUNG_BINH", "KEM"), thresholds):
        if value >= threshold:
            return code
    return "RAT_KEM"


def _dimension(code, value, unit, text):
    return {
        "level": code,
        "label_vi": LEVELS[code][0],
        "value": value,
        "unit": unit,
        "text_vi": text,
    }


def _baseline_summary(request):
    receivers = sorted(
        (r for r in request.receivers
         if r.enabled and r.id != request.failed_receiver_id),
        key=lambda r: r.id,
    )
    pairs = []
    for index, first in enumerate(receivers):
        for second in receivers[index + 1:]:
            distance = ground_distance_km(
                first.lat, first.lon, second.lat, second.lon)
            pairs.append({
                "receiver_ids": [first.id, second.id],
                "receiver_names": [first.name, second.name],
                "distance_km": distance,
            })
    distances = [x["distance_km"] for x in pairs]
    very_close = [x for x in pairs if x["distance_km"] < 50]
    main = [x for x in pairs if 150 <= x["distance_km"] < 250]
    long_pairs = [x for x in pairs if 250 <= x["distance_km"] <= 350]
    very_long = [x for x in pairs if x["distance_km"] > 350]
    if not distances:
        return {
            "min_km": None, "median_km": None, "max_km": None,
            "very_close_pairs": [], "main_pairs_count": 0,
            "long_pairs_count": 0, "very_long_pairs_count": 0,
            "text_vi": "Chưa có đủ hai trạm để thống kê khoảng cách.",
        }
    pieces = [
        "Khoảng cách trạm nhỏ nhất, trung vị và lớn nhất lần lượt là "
        f"{_number_vi(min(distances))}, {_number_vi(statistics.median(distances))} "
        f"và {_number_vi(max(distances))} km."
    ]
    if very_close:
        names = ", ".join("–".join(x["receiver_names"]) for x in very_close)
        pieces.append(
            f"Có {len(very_close)} cặp dưới 50 km ({names}); theo diễn giải "
            "quy hoạch nội bộ, các cặp này cung cấp ít hướng quan sát độc lập hơn.")
    pieces.append(
        f"Có {len(main)} cặp trong dải 150–<250 km, {len(long_pairs)} cặp "
        "trong dải 250–350 km và "
        f"{len(very_long)} cặp trên 350 km.")
    return {
        "min_km": min(distances),
        "median_km": statistics.median(distances),
        "max_km": max(distances),
        "very_close_pairs": very_close,
        "main_pairs_count": len(main),
        "long_pairs_count": len(long_pairs),
        "very_long_pairs_count": len(very_long),
        "text_vi": " ".join(pieces),
    }


def _p95_dimension(median, p90, timing_noise):
    if median is None or p90 is None:
        return _dimension(
            "KHONG_DU_DU_LIEU", None, "m",
            "Chưa có đủ điểm MLAT để tổng hợp sai số dự kiến 95%.")
    if median <= 250 and p90 <= 500:
        code = "RAT_TOT"
    elif median <= 500 and p90 <= 1500:
        code = "TOT"
    elif median <= 1500 and p90 <= 5000:
        code = "TRUNG_BINH"
    elif median <= 5000:
        code = "KEM"
    else:
        code = "RAT_KEM"
    text = (
        f"Trung vị là {_number_vi(median, 0)} m; P90 theo bản đồ là "
        f"{_number_vi(p90, 0)} m, với sai số thời gian giả định "
        f"{_number_vi(timing_noise, 2)} µs. Đây là dự báo của mô hình, "
        "không phải sai số đo thực tế.")
    if median <= 500 and p90 > 1500:
        text += (
            " Sai số điển hình thấp nhưng còn một số vùng có sai số tăng mạnh.")
    return _dimension(code, median, "m", text)


def _dependency(summary):
    entries = summary.get("receiver_importance") or []
    minimum = UX_THRESHOLDS["dependency_min_samples"]
    candidates = [
        x for x in entries
        if x.get("samples", 0) >= minimum
        and x.get("median_p95_ratio_without_receiver") is not None
        and x.get("p90_p95_ratio_without_receiver") is not None
    ]
    if not candidates:
        return {
            "level": "KHONG_DU_DU_LIEU",
            "label_vi": LEVELS["KHONG_DU_DU_LIEU"][0],
            "receiver_id": None,
            "receiver_name": None,
            "median_ratio": None,
            "p90_ratio": None,
            "samples": 0,
            "sample_fraction_percent": 0,
            "tied": False,
            "text_vi": "Chưa đủ dữ liệu để xác định trạm quan trọng nhất.",
            "receivers": entries,
        }
    ranked = sorted(
        candidates,
        key=lambda x: (
            -x["median_p95_ratio_without_receiver"],
            -x["p90_p95_ratio_without_receiver"],
            -x.get("sample_fraction_percent", 0),
            x["id"],
        ),
    )
    best = ranked[0]
    tied = len(ranked) > 1 and all(
        math.isclose(best[key], ranked[1][key], rel_tol=0, abs_tol=1e-12)
        for key in ("median_p95_ratio_without_receiver",
                    "p90_p95_ratio_without_receiver")
    )
    pronounced = (
        best["median_p95_ratio_without_receiver"] > 1.05
        or best["p90_p95_ratio_without_receiver"] > 1.10
    )
    if not pronounced:
        text = (
            "Chưa thấy một trạm phụ thuộc nổi trội; bỏ từng trạm không làm "
            "best P95 tăng đáng kể tại các vùng có đủ alternative.")
        receiver_id = receiver_name = None
        level = "TOT"
    else:
        tie_text = " Có đồng hạng theo median và P90; ID được dùng để tie-break." if tied else ""
        text = (
            f"Mạng phụ thuộc nhiều nhất vào {best['name']}. Khi không sử dụng "
            f"trạm này, best P95 tăng trung vị "
            f"{_number_vi(best['median_p95_ratio_without_receiver'], 2)} lần "
            f"trên {best['samples']} điểm có đủ dữ liệu đánh giá.{tie_text}")
        receiver_id, receiver_name, level = best["id"], best["name"], "KEM"
    return {
        "level": level,
        "label_vi": LEVELS[level][0],
        "receiver_id": receiver_id,
        "receiver_name": receiver_name,
        "median_ratio": best["median_p95_ratio_without_receiver"],
        "p90_ratio": best["p90_p95_ratio_without_receiver"],
        "samples": best["samples"],
        "sample_fraction_percent": best.get("sample_fraction_percent", 0),
        "tied": tied,
        "text_vi": text,
        "receivers": entries,
    }


def build_assessment(result, request):
    """Return a byte-stable, JSON-safe Vietnamese assessment."""
    summary = result["summary"]
    strict = summary["geometry_strategy"] == "strict_4"
    reception_value = summary["four_plus_rx_coverage_percent"]
    reception_code = _percent_level(
        reception_value, UX_THRESHOLDS["reception_percent"])
    reception = _dimension(
        reception_code, reception_value, "%",
        f"{_number_vi(reception_value)}% vùng có ít nhất bốn trạm thu được "
        "tín hiệu theo nguồn vùng thu đã chọn.")

    good = summary["good_percent"]
    good_acceptable = summary["good_acceptable_percent"]
    if good >= 75 and good_acceptable >= 90:
        geometry_code = "RAT_TOT"
    elif good >= 50 and good_acceptable >= 75:
        geometry_code = "TOT"
    elif good >= 25 and good_acceptable >= 50:
        geometry_code = "TRUNG_BINH"
    elif good >= 10:
        geometry_code = "KEM"
    else:
        geometry_code = "RAT_KEM"
    median_condition = (
        summary.get("median_condition") if strict
        else summary.get("median_best_condition"))
    condition_label = (
        "Tốt" if median_condition is not None and median_condition <= 10
        else "Trung bình" if median_condition is not None and median_condition <= 30
        else "Kém" if median_condition is not None else "Chưa đủ dữ liệu")
    geometry = _dimension(
        geometry_code, good, "%",
        f"{_number_vi(good)}% vùng có tổ hợp tốt nhất đạt lớp lõi GOOD; "
        f"{_number_vi(good_acceptable)}% đạt GOOD hoặc ACCEPTABLE. "
        f"Độ nhạy bố trí ở mức {condition_label.lower()}.")
    geometry["condition_label_vi"] = condition_label
    geometry["median_condition"] = median_condition
    geometry["good_acceptable_percent"] = good_acceptable

    branch_safe = (
        summary.get("branch_safe_percent") if strict
        else summary.get("best_branch_safe_percent"))
    branch_good = (
        summary.get("branch_good_percent") if strict
        else summary.get("best_branch_good_percent"))
    branch_code = _percent_level(
        branch_good, UX_THRESHOLDS["branch_good_percent"])
    branch = _dimension(
        branch_code, branch_good, "%",
        f"{_number_vi(branch_good)}% vùng có độ tách biệt nghiệm của tổ hợp "
        "được đánh giá đạt ngưỡng GOOD từ 1,0 µs; "
        f"{_number_vi(branch_safe)}% đạt điều kiện branch-safe từ 0,5 µs.")
    branch["branch_safe_percent"] = branch_safe
    branch["formula"] = (
        "100 * số grid point có branch separation của best subset >= 1.0 us "
        "/ tổng grid point; strict-4 dùng selected subset")

    median_p50 = (
        summary.get("median_predicted_p50_m") if strict
        else summary.get("median_best_p50_m"))
    median_p95 = (
        summary.get("median_predicted_p95_m") if strict
        else summary.get("median_best_p95_m"))
    p90_p95 = (
        summary.get("p90_predicted_p95_m") if strict
        else summary.get("p90_best_p95_m"))
    p95 = _p95_dimension(median_p95, p90_p95, request.timing_noise_us)
    p95["median_p50_m"] = median_p50
    p95["median_p95_m"] = median_p95
    p95["p90_p95_m"] = p90_p95
    p95["timing_noise_us"] = request.timing_noise_us

    if strict:
        one_good = good
        two_good = three_good = 0.0
        median_fraction = good / 100
    else:
        one_good = summary["one_good_subset_percent"]
        two_good = summary["robust_good_fraction_percent"]
        three_good = summary["three_good_subsets_percent"]
        median_fraction = summary["median_good_subset_fraction"]
    redundancy_code = _percent_level(
        two_good, UX_THRESHOLDS["redundancy_percent"])
    redundancy = _dimension(
        redundancy_code, two_good, "%",
        f"{_number_vi(one_good)}% vùng có ít nhất một, "
        f"{_number_vi(two_good)}% có ít nhất hai và "
        f"{_number_vi(three_good)}% có ít nhất ba tổ hợp 4 trạm GOOD.")
    redundancy.update({
        "one_good_subset_percent": one_good,
        "two_good_subsets_percent": two_good,
        "three_good_subsets_percent": three_good,
        "median_good_subset_fraction": median_fraction,
    })

    eligible_count = len([
        r for r in request.receivers
        if r.enabled and r.id != request.failed_receiver_id])
    if strict or eligible_count < 5:
        n_minus_one = _dimension(
            "KHONG_AP_DUNG", 0.0, "%",
            "Mạng hiện không có ít nhất năm trạm eligible để đánh giá mất "
            "bất kỳ một trạm mà vẫn còn tổ hợp 4 trạm GOOD.")
    else:
        value = summary["n_minus_1_survivable_percent"]
        code = _percent_level(value, UX_THRESHOLDS["n_minus_1_percent"])
        n_minus_one = _dimension(
            code, value, "%",
            f"{_number_vi(value)}% vùng vẫn còn ít nhất một tổ hợp 4 trạm "
            "GOOD sau mọi kịch bản giả lập mất một trạm.")

    dependency = _dependency(summary)
    baseline = _baseline_summary(request)

    component_codes = [
        reception["level"], geometry["level"], branch["level"], p95["level"]]
    component_scores = [
        LEVELS[x][1] for x in component_codes if LEVELS[x][1] is not None]
    score = min(component_scores) if component_scores else 0
    # Redundancy is a conservative cap, not a weighted numeric score.
    if n_minus_one["level"] in ("KHONG_AP_DUNG", "RAT_KEM", "KEM"):
        score = min(score, 2)
    elif n_minus_one["level"] == "TRUNG_BINH":
        score = min(score, 3)
    if redundancy["level"] in ("RAT_KEM", "KEM"):
        score = min(score, 2)
    overall_code, overall_label = OVERALL[score]

    paragraphs = [
        {
            "RAT_TOT": "Vùng thu chung rất rộng; hầu hết khu vực có ít nhất bốn trạm cùng thu được tín hiệu.",
            "TOT": "Vùng thu chung rộng theo nguồn reception đã chọn.",
            "TRUNG_BINH": "Vùng thu chung ở mức trung bình; một phần đáng kể khu vực vẫn chưa đủ bốn trạm.",
            "KEM": "Vùng thu chung còn hạn chế; nhiều khu vực chưa đủ bốn trạm cùng thu.",
            "RAT_KEM": "Vùng thu chung rất hạn chế theo giả định reception hiện tại.",
        }.get(reception_code, "Chưa đủ dữ liệu đánh giá vùng thu chung."),
        {
            "RAT_TOT": "Bố trí trạm rất thuận lợi theo phân bố lớp chất lượng lõi.",
            "TOT": "Bố trí trạm nhìn chung thuận lợi theo mô hình hiện tại.",
            "TRUNG_BINH": "Bố trí trạm sử dụng được nhưng chất lượng chưa đồng đều.",
            "KEM": "Bố trí trạm còn yếu ở nhiều điểm trong vùng giám sát.",
            "RAT_KEM": "Phần lớn vùng chưa đạt lớp chất lượng bố trí mong muốn.",
        }.get(geometry_code, "Chưa đủ dữ liệu đánh giá bố trí trạm."),
        {
            "RAT_TOT": "Các nghiệm cạnh tranh được tách rõ ở gần như toàn bộ vùng.",
            "TOT": "Độ tách biệt nghiệm tốt ở phần lớn vùng.",
            "TRUNG_BINH": "Độ tách biệt nghiệm chưa đồng đều trên toàn vùng.",
            "KEM": "Nhiều vùng còn nguy cơ có nghiệm cạnh tranh khó phân biệt.",
            "RAT_KEM": "Độ tách biệt nghiệm yếu trên phần lớn vùng phân tích.",
        }.get(branch_code, "Chưa đủ dữ liệu đánh giá độ tách biệt nghiệm."),
        p95["text_vi"].split(" Đây là")[0].rstrip(".") + ".",
    ]
    if (median_p95 is not None and p90_p95 is not None
            and median_p95 <= 500 and p90_p95 > 1500):
        paragraphs.append(
            "Sai số điển hình thấp nhưng còn một số vùng có sai số tăng mạnh.")
    worst_good = summary.get("worst_good_percent")
    if worst_good is not None and good - worst_good >= 25:
        paragraphs.append(
            "Mạng có tổ hợp mạnh nhưng chất lượng giữa các tổ hợp chưa đồng đều.")
    paragraphs.append(redundancy["text_vi"])
    paragraphs.append(n_minus_one["text_vi"])
    paragraphs.append(dependency["text_vi"])
    if len(paragraphs) > 8:
        paragraphs = paragraphs[:6] + paragraphs[-2:]
    paragraph = " ".join(paragraphs)

    source_counts = summary.get("reception_source_counts", {})
    context = {
        "target_altitude_m": request.target_altitude_m,
        "timing_noise_us": request.timing_noise_us,
        "grid_step_km": request.grid_step_km,
        "geometry_strategy": request.geometry_strategy,
        "enabled_receiver_count": eligible_count,
        "reception_model_counts": {
            "outline": source_counts.get("outline", 0),
            "simulated": source_counts.get("simulated", 0),
        },
        "grid_point_count": summary["grid_points"],
    }
    return {
        "version": "phase35-v1",
        "ux_interpretation_only": True,
        "overall": {
            "level": overall_code,
            "label_vi": overall_label,
            "policy": (
                "Mức thấp nhất của vùng thu chung, bố trí, branch và P95; "
                "sau đó giới hạn tối đa KHÁ nếu N-1 không áp dụng/rất thấp "
                "hoặc dự phòng nhiều tổ hợp thấp."),
        },
        "reception": reception,
        "geometry": geometry,
        "branch": branch,
        "p95": p95,
        "redundancy": redundancy,
        "n_minus_1": n_minus_one,
        "dependency": dependency,
        "baseline": baseline,
        "context": context,
        "paragraph_vi": paragraph,
        "ux_thresholds": UX_THRESHOLDS,
        "core_quality_note_vi": (
            "GOOD/ACCEPTABLE/POOR/VERY_POOR là lớp chất lượng lõi. "
            "Rất tốt/Tốt/Trung bình/Kém/Rất kém trong panel này chỉ là "
            "diễn giải UX của metric tổng hợp."),
    }
