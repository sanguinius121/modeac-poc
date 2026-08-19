"""Stable quality thresholds shared by all geometry consumers."""


def classify(p95, condition, branch_sep):
    if p95 <= 500 and condition <= 10 and branch_sep >= 1.0:return "GOOD"
    if p95 <= 1500 and condition <= 30 and branch_sep >= 0.5:return "ACCEPTABLE"
    if p95 <= 5000 and condition <= 100 and branch_sep >= 0.2:return "POOR"
    return "VERY POOR"
