"""
PRONOSTIA Step 5: temperature-regressed vibration residual T2.

Goal:
Compare the accepted vibration-only T2 curve against a temperature-corrected
variant where each vibration feature is linearly regressed on temperature
features using the assumed healthy baseline window. The T2 model is then built
on residual vibration features.

This tests the intended architecture:
  temperature is a covariate to remove, not a health feature to directly score.
"""
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import spearmanr


ROOT = os.path.dirname(__file__)
BEARING = "Bearing1_1"
BASE = os.path.join(
    ROOT,
    "data",
    "femto_tmp",
    "ieee-phm-2012-data-challenge-dataset-master",
    "Learning_set",
    BEARING,
)
FEAT_CSV = os.path.join(ROOT, "outputs", "step1_features", f"{BEARING}_features.csv")
OUT_DIR = os.path.join(ROOT, "outputs", "step5_temp_regression")
os.makedirs(OUT_DIR, exist_ok=True)

HEALTH_FRAC = 0.10
K_CONSECUTIVE = 5
VIB_FEATURES = ["rms_h", "kurt_h", "crest_h", "p2p_h"]


def first_consecutive_alarm(values, threshold, k):
    run = 0
    for i, above in enumerate(values > threshold):
        run = run + 1 if above else 0
        if run >= k:
            return i - k + 1
    return -1


def load_temp_features(n_acc):
    temp_files = sorted(glob.glob(os.path.join(BASE, "temp_*.csv")))
    rows = []
    for path in temp_files:
        d = np.genfromtxt(path, delimiter=",")
        temp = d[:, 4].astype(float)
        rows.append([
            temp.mean(),
            temp.std(),
            temp[-1] - temp[0],
        ])
    temp_features = np.asarray(rows)
    src = np.linspace(0, n_acc - 1, len(temp_features))
    dst = np.arange(n_acc)
    interp = np.column_stack([
        np.interp(dst, src, temp_features[:, j])
        for j in range(temp_features.shape[1])
    ])
    names = ["temp_mean", "temp_std", "temp_delta"]
    return interp, names, len(temp_files)


def residualize_by_temperature(X, T, h_end):
    # Add intercept. Fit on baseline only to avoid leaking degradation into the
    # temperature model.
    A = np.column_stack([np.ones(len(T)), T])
    coef, *_ = np.linalg.lstsq(A[:h_end], X[:h_end], rcond=None)
    pred = A @ coef
    residual = X - pred

    # Preserve the baseline feature center so residual curves remain comparable
    # to raw features in scale and sign.
    residual += X[:h_end].mean(axis=0)
    return residual, coef


def raw_t2(X, h_end):
    Xh = X[:h_end]
    mu_std = Xh.mean(axis=0)
    sd_std = Xh.std(axis=0) + 1e-12
    Xz = (X - mu_std) / sd_std
    Xhz = Xz[:h_end]
    mu = Xhz.mean(axis=0)
    cov = np.cov(Xhz, rowvar=False)
    cov_inv = np.linalg.pinv(cov)
    d = Xz - mu
    return np.einsum("ij,jk,ik->i", d, cov_inv, d)


def score_curve(name, X, idx):
    n = len(idx)
    h_end = int(HEALTH_FRAC * n)
    t2 = raw_t2(X, h_end)
    ucl = np.quantile(t2[:h_end], 0.99)
    health = np.exp(-3.0 * t2 / (ucl + 1e-12))
    alarm = first_consecutive_alarm(t2, ucl, K_CONSECUTIVE)
    far = np.mean(t2[:h_end] > ucl)

    deg_slice = slice(h_end, n)
    time_to_fail = (n - 1) - idx[deg_slice]
    rho, _ = spearmanr(health[deg_slice], time_to_fail)
    h_deg = health[h_end:]
    roughness = np.mean(np.abs(np.diff(h_deg)))
    diff_p95 = np.quantile(np.abs(np.diff(h_deg)), 0.95)

    return {
        "name": name,
        "t2": t2,
        "ucl": ucl,
        "health": health,
        "alarm": alarm,
        "alarm_pct": 100 * alarm / n if alarm >= 0 else np.nan,
        "lead_min": (n - alarm) * 10 / 60 if alarm >= 0 else np.nan,
        "far": far,
        "rho": rho,
        "roughness": roughness,
        "diff_p95": diff_p95,
    }


def save_summary(rows, temp_names, temp_count):
    path = os.path.join(OUT_DIR, f"{BEARING}_temp_regression_summary.csv")
    header = [
        "model",
        "far_pct",
        "spearman_health_ttf",
        "alarm_idx",
        "alarm_life_pct",
        "lead_min",
        "health_roughness_mean_abs_diff",
        "health_diff_p95",
        "temp_features",
        "temp_files",
    ]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join([
            row["name"],
            f"{row['far'] * 100:.3f}",
            f"{row['rho']:.3f}",
            str(row["alarm"]),
            f"{row['alarm_pct']:.2f}",
            f"{row['lead_min']:.2f}",
            f"{row['roughness']:.6f}",
            f"{row['diff_p95']:.6f}",
            "|".join(temp_names),
            str(temp_count),
        ]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return path


def save_plot(idx, temp_mean, raw_X, residual_X, rows):
    fig, axes = plt.subplots(5, 1, figsize=(12, 15), sharex=True)

    axes[0].plot(idx, temp_mean, color="C1", lw=0.8)
    axes[0].set_ylabel("temp mean")
    axes[0].set_title(f"{BEARING} temperature covariate")
    axes[0].grid(alpha=0.3)

    for j, name in enumerate(VIB_FEATURES):
        axes[1].plot(idx, raw_X[:, j], lw=0.5, label=f"raw {name}")
        axes[1].plot(idx, residual_X[:, j], lw=0.5, ls="--", label=f"resid {name}")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("feature value")
    axes[1].set_title("Raw vs temperature-regressed vibration features")
    axes[1].legend(fontsize=7, ncol=2)
    axes[1].grid(alpha=0.3)

    for row in rows:
        axes[2].plot(
            idx,
            row["health"],
            lw=0.7,
            label=(
                f"{row['name']} | rho={row['rho']:.2f}, "
                f"rough={row['roughness']:.3f}, alarm={row['alarm_pct']:.0f}%"
            ),
        )
    axes[2].set_ylabel("health")
    axes[2].set_title("Health score comparison")
    axes[2].legend(fontsize=8)
    axes[2].grid(alpha=0.3)

    for row in rows:
        axes[3].plot(idx, row["t2"] / (row["ucl"] + 1e-12), lw=0.6, label=row["name"])
    axes[3].axhline(1.0, color="k", ls="--", lw=0.8)
    axes[3].set_yscale("log")
    axes[3].set_ylabel("T2 / UCL")
    axes[3].set_title("Normalized T2 comparison")
    axes[3].legend(fontsize=8)
    axes[3].grid(alpha=0.3)

    for row in rows:
        axes[4].plot(idx[1:], np.abs(np.diff(row["health"])), lw=0.45, label=row["name"])
    axes[4].set_yscale("log")
    axes[4].set_ylabel("|diff health|")
    axes[4].set_xlabel("snapshot index")
    axes[4].set_title("Health-score jump size, lower is smoother")
    axes[4].legend(fontsize=8)
    axes[4].grid(alpha=0.3)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, f"{BEARING}_temp_regression_comparison.png")
    fig.savefig(path, dpi=110)
    return path


def main():
    data = np.genfromtxt(FEAT_CSV, delimiter=",", names=True)
    idx = data["idx"].astype(int)
    h_end = int(HEALTH_FRAC * len(idx))
    raw_X = np.column_stack([data[name] for name in VIB_FEATURES])
    temp_X, temp_names, temp_count = load_temp_features(len(idx))
    residual_X, coef = residualize_by_temperature(raw_X, temp_X, h_end)

    rows = [
        score_curve("vib4_raw_t2", raw_X, idx),
        score_curve("vib4_temp_residual_t2", residual_X, idx),
    ]

    print(f"=== Step 5 temperature-regressed residual T2 | {BEARING} ===")
    print(f"temperature files={temp_count}, features={', '.join(temp_names)}")
    print("regression coefficient matrix shape:", coef.shape)
    for row in rows:
        print(
            f"{row['name']}: FAR={row['far'] * 100:.2f}%, "
            f"Spearman={row['rho']:.3f}, alarm={row['alarm']} "
            f"({row['alarm_pct']:.1f}%), lead={row['lead_min']:.1f}min, "
            f"roughness={row['roughness']:.4f}, diff_p95={row['diff_p95']:.4f}"
        )

    summary_path = save_summary(rows, temp_names, temp_count)
    plot_path = save_plot(idx, temp_X[:, 0], raw_X, residual_X, rows)
    print(f"\nsaved summary -> {summary_path}")
    print(f"saved plot -> {plot_path}")


if __name__ == "__main__":
    main()
