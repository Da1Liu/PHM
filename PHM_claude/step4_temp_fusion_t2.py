"""
PRONOSTIA Step 4: cross-sensor fusion with vibration + temperature.

This checks whether adding a non-vibration sensor can make the health score
more stable/smoother while preserving degradation sensitivity.

Experiment target:
  Bearing1_1, because it has both long vibration run-to-failure data and
  temperature files.

Compared models:
  A) vib_h_4_raw_t2: horizontal vibration 4 features, raw covariance T2
  B) vib_h_4_temp_raw_t2: vibration + interpolated temperature features,
     raw covariance T2
  C) vib_h_4_temp_pca_t2: vibration + interpolated temperature features,
     PCA + T2 with 95% explained variance
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
OUT_DIR = os.path.join(ROOT, "outputs", "step4_temp_fusion")
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
            temp.min(),
            temp.max(),
        ])
    temp_features = np.asarray(rows)

    # Temperature is sampled every ~60s, acceleration every 10s.
    # Use sequence-position interpolation rather than wall-clock parsing.
    src = np.linspace(0, n_acc - 1, len(temp_features))
    dst = np.arange(n_acc)
    interp = np.column_stack([
        np.interp(dst, src, temp_features[:, j])
        for j in range(temp_features.shape[1])
    ])
    names = ["temp_mean", "temp_std", "temp_delta", "temp_min", "temp_max"]
    return interp, names, len(temp_files)


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
    return np.einsum("ij,jk,ik->i", d, cov_inv, d), None


def pca_t2(X, h_end, var_keep=0.95):
    Xh = X[:h_end]
    mu_std = Xh.mean(axis=0)
    sd_std = Xh.std(axis=0) + 1e-12
    Xz = (X - mu_std) / sd_std
    Xhz = Xz[:h_end]

    _, s, vt = np.linalg.svd(Xhz, full_matrices=False)
    explained = (s**2) / max(len(Xhz) - 1, 1)
    ratio = explained / explained.sum()
    k = int(np.searchsorted(np.cumsum(ratio), var_keep) + 1)
    W = vt[:k].T
    lam = explained[:k] + 1e-12
    Z = Xz @ W
    t2 = np.sum((Z**2) / lam, axis=1)
    return t2, {"k": k, "explained_ratio": float(np.sum(ratio[:k]))}


def score_curve(name, X, idx, method):
    n = len(idx)
    h_end = int(HEALTH_FRAC * n)
    if method == "raw":
        t2, extra = raw_t2(X, h_end)
    elif method == "pca":
        t2, extra = pca_t2(X, h_end)
    else:
        raise ValueError(method)

    ucl = np.quantile(t2[:h_end], 0.99)
    health = np.exp(-3.0 * t2 / (ucl + 1e-12))
    alarm = first_consecutive_alarm(t2, ucl, K_CONSECUTIVE)
    far = np.mean(t2[:h_end] > ucl)

    deg_slice = slice(h_end, n)
    time_to_fail = (n - 1) - idx[deg_slice]
    rho, _ = spearmanr(health[deg_slice], time_to_fail)

    # Lower values mean smoother health curve. We calculate outside baseline to
    # avoid rewarding a model for being flat only in the assumed healthy window.
    h_deg = health[h_end:]
    roughness = np.mean(np.abs(np.diff(h_deg)))
    diff_p95 = np.quantile(np.abs(np.diff(h_deg)), 0.95)

    return {
        "name": name,
        "method": method,
        "t2": t2,
        "health": health,
        "ucl": ucl,
        "far": far,
        "rho": rho,
        "alarm": alarm,
        "alarm_pct": 100 * alarm / n if alarm >= 0 else np.nan,
        "lead_min": (n - alarm) * 10 / 60 if alarm >= 0 else np.nan,
        "roughness": roughness,
        "diff_p95": diff_p95,
        "extra": extra or {},
    }


def save_summary(rows, temp_count):
    path = os.path.join(OUT_DIR, f"{BEARING}_temp_fusion_summary.csv")
    header = [
        "model",
        "method",
        "features",
        "far_pct",
        "spearman_health_ttf",
        "alarm_idx",
        "alarm_life_pct",
        "lead_min",
        "health_roughness_mean_abs_diff",
        "health_diff_p95",
        "pca_k",
        "pca_explained_ratio",
        "temp_files",
    ]
    lines = [",".join(header)]
    for row in rows:
        extra = row["extra"]
        lines.append(",".join([
            row["name"],
            row["method"],
            str(row["n_features"]),
            f"{row['far'] * 100:.3f}",
            f"{row['rho']:.3f}",
            str(row["alarm"]),
            f"{row['alarm_pct']:.2f}",
            f"{row['lead_min']:.2f}",
            f"{row['roughness']:.6f}",
            f"{row['diff_p95']:.6f}",
            str(extra.get("k", "")),
            f"{extra.get('explained_ratio', np.nan):.4f}" if "explained_ratio" in extra else "",
            str(temp_count),
        ]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return path


def save_plot(idx, temp_mean, rows):
    fig, axes = plt.subplots(4, 1, figsize=(12, 13), sharex=True)

    axes[0].plot(idx, temp_mean, color="C1", lw=0.8)
    axes[0].set_ylabel("temp mean")
    axes[0].set_title(f"{BEARING} temperature aligned to vibration snapshots")
    axes[0].grid(alpha=0.3)

    for row in rows:
        label = (
            f"{row['name']} | rho={row['rho']:.2f}, "
            f"rough={row['roughness']:.3f}, alarm={row['alarm_pct']:.0f}%"
        )
        axes[1].plot(idx, row["health"], lw=0.65, label=label)
    axes[1].set_ylabel("health")
    axes[1].set_title("Health score comparison")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    for row in rows:
        axes[2].plot(idx, row["t2"] / (row["ucl"] + 1e-12), lw=0.55, label=row["name"])
    axes[2].axhline(1.0, color="k", ls="--", lw=0.8)
    axes[2].set_yscale("log")
    axes[2].set_ylabel("T2 / UCL")
    axes[2].set_title("Normalized T2 comparison")
    axes[2].legend(fontsize=8)
    axes[2].grid(alpha=0.3)

    for row in rows:
        diff = np.abs(np.diff(row["health"]))
        axes[3].plot(idx[1:], diff, lw=0.45, label=row["name"])
    axes[3].set_ylabel("|diff health|")
    axes[3].set_xlabel("snapshot index")
    axes[3].set_yscale("log")
    axes[3].set_title("Health-score jump size, lower is smoother")
    axes[3].legend(fontsize=8)
    axes[3].grid(alpha=0.3)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, f"{BEARING}_temp_fusion_comparison.png")
    fig.savefig(path, dpi=110)
    return path


def main():
    data = np.genfromtxt(FEAT_CSV, delimiter=",", names=True)
    idx = data["idx"].astype(int)
    temp, temp_names, temp_count = load_temp_features(len(idx))

    X_vib = np.column_stack([data[name] for name in VIB_FEATURES])
    X_fused = np.column_stack([X_vib, temp])

    configs = [
        ("vib4_raw_t2", X_vib, "raw"),
        ("vib4_temp_raw_t2", X_fused, "raw"),
        ("vib4_temp_pca_t2", X_fused, "pca"),
    ]

    rows = []
    print(f"=== Step 4 temperature fusion T2 | {BEARING} ===")
    print(f"temperature files={temp_count}, vibration snapshots={len(idx)}")
    print("temperature features:", ", ".join(temp_names))
    for name, X, method in configs:
        row = score_curve(name, X, idx, method)
        row["n_features"] = X.shape[1]
        rows.append(row)
        pca_info = ""
        if row["extra"]:
            pca_info = (
                f", pca_k={row['extra']['k']}, "
                f"explained={row['extra']['explained_ratio']:.3f}"
            )
        print(
            f"{name}: features={X.shape[1]}, FAR={row['far'] * 100:.2f}%, "
            f"Spearman={row['rho']:.3f}, alarm={row['alarm']} "
            f"({row['alarm_pct']:.1f}%), lead={row['lead_min']:.1f}min, "
            f"roughness={row['roughness']:.4f}, diff_p95={row['diff_p95']:.4f}"
            f"{pca_info}"
        )

    summary_path = save_summary(rows, temp_count)
    plot_path = save_plot(idx, temp[:, 0], rows)
    print(f"\nsaved summary -> {summary_path}")
    print(f"saved plot -> {plot_path}")


if __name__ == "__main__":
    main()
