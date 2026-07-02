"""
PRONOSTIA health-curve validation - Step 3: multi-bearing check.

Purpose:
Run the same minimal Step 2 chain on all Learning_set bearings:
raw acceleration snapshots -> 4 horizontal time-domain features ->
first-10% health baseline -> Hotelling T2 -> health curve -> debounced alarm.

This is intentionally not a convergence/refinement step. It only checks whether
the already accepted minimal chain reproduces across the six PRONOSTIA bearings.
"""
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import f as f_dist
from scipy.stats import spearmanr


ROOT = os.path.dirname(__file__)
BASE = os.path.join(
    ROOT,
    "data",
    "femto_tmp",
    "ieee-phm-2012-data-challenge-dataset-master",
    "Learning_set",
)
OUT_DIR = os.path.join(ROOT, "outputs", "step3_multi_bearing")
os.makedirs(OUT_DIR, exist_ok=True)

FEATURES = ["rms_h", "kurt_h", "crest_h", "p2p_h"]
HEALTH_FRAC = 0.10
K_CONSECUTIVE = 5
COL_H = 4
COL_V = 5


def extract_features(signal):
    x = signal.astype(np.float64)
    rms = np.sqrt(np.mean(x**2))
    peak = np.max(np.abs(x))
    mean = np.mean(x)
    std = np.std(x)
    kurt = np.mean(((x - mean) / (std + 1e-12)) ** 4)
    crest = peak / (rms + 1e-12)
    p2p = np.max(x) - np.min(x)
    return rms, kurt, crest, p2p


def feature_csv_path(bearing):
    return os.path.join(OUT_DIR, f"{bearing}_features.csv")


def load_or_extract_features(bearing):
    csv_path = feature_csv_path(bearing)
    if os.path.exists(csv_path):
        return np.genfromtxt(csv_path, delimiter=",", names=True)

    files = sorted(glob.glob(os.path.join(BASE, bearing, "acc_*.csv")))
    rows = []
    for i, path in enumerate(files):
        d = np.genfromtxt(path, delimiter=",")
        fh = extract_features(d[:, COL_H])
        fv = extract_features(d[:, COL_V])
        rows.append((i, *fh, *fv))

    cols = [
        "idx",
        "rms_h", "kurt_h", "crest_h", "p2p_h",
        "rms_v", "kurt_v", "crest_v", "p2p_v",
    ]
    data = np.array(rows)
    np.savetxt(csv_path, data, delimiter=",", header=",".join(cols), comments="")
    return np.genfromtxt(csv_path, delimiter=",", names=True)


def first_consecutive_alarm(values, threshold, k):
    run = 0
    for i, is_above in enumerate(values > threshold):
        run = run + 1 if is_above else 0
        if run >= k:
            return i - k + 1
    return -1


def score_bearing(data):
    idx = data["idx"].astype(int)
    n = len(idx)
    h_end = int(HEALTH_FRAC * n)
    X = np.column_stack([data[name] for name in FEATURES])

    Xh = X[:h_end]
    mu_std = Xh.mean(axis=0)
    sd_std = Xh.std(axis=0) + 1e-12
    Xz = (X - mu_std) / sd_std
    Xhz = Xz[:h_end]

    mu = Xhz.mean(axis=0)
    cov = np.cov(Xhz, rowvar=False)
    cov_inv = np.linalg.pinv(cov)
    d = Xz - mu
    t2 = np.einsum("ij,jk,ik->i", d, cov_inv, d)

    ucl_emp = np.quantile(t2[:h_end], 0.99)
    p = len(FEATURES)
    m = h_end
    fcrit = f_dist.ppf(0.99, p, m - p)
    ucl_f = p * (m - 1) * (m + 1) / (m * (m - p)) * fcrit

    t2_ref = np.median(t2[:h_end]) + 1e-12
    health = np.exp(-t2 / (t2_ref * 10))
    score = t2 / (ucl_emp + 1e-12)

    alarm_emp = first_consecutive_alarm(t2, ucl_emp, K_CONSECUTIVE)
    far = np.mean(t2[:h_end] > ucl_emp)
    deg_slice = slice(h_end, n)
    time_to_fail = (n - 1) - idx[deg_slice]
    rho, _ = spearmanr(health[deg_slice], time_to_fail)

    return {
        "n": n,
        "h_end": h_end,
        "t2": t2,
        "health": health,
        "score": score,
        "ucl_emp": ucl_emp,
        "ucl_f": ucl_f,
        "far": far,
        "rho_health_ttf": rho,
        "alarm_emp": alarm_emp,
        "alarm_life_pct": 100 * alarm_emp / n if alarm_emp >= 0 else np.nan,
        "lead_snaps": n - alarm_emp if alarm_emp >= 0 else np.nan,
    }


def save_summary(summary_rows):
    path = os.path.join(OUT_DIR, "multi_bearing_summary.csv")
    header = [
        "bearing",
        "n",
        "health_window",
        "far_pct",
        "spearman_health_ttf",
        "alarm_idx_emp",
        "alarm_life_pct",
        "lead_snaps",
        "lead_min",
        "ucl_emp",
        "ucl_f",
    ]
    lines = [",".join(header)]
    for row in summary_rows:
        lines.append(",".join([
            row["bearing"],
            str(row["n"]),
            str(row["h_end"]),
            f"{row['far'] * 100:.3f}",
            f"{row['rho_health_ttf']:.3f}",
            str(row["alarm_emp"]),
            f"{row['alarm_life_pct']:.2f}",
            f"{row['lead_snaps']:.0f}",
            f"{row['lead_snaps'] * 10 / 60:.1f}",
            f"{row['ucl_emp']:.3f}",
            f"{row['ucl_f']:.3f}",
        ]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return path


def save_plot(results):
    bearings = list(results.keys())
    fig, axes = plt.subplots(len(bearings), 2, figsize=(13, 3.1 * len(bearings)))
    if len(bearings) == 1:
        axes = axes.reshape(1, -1)

    for r, bearing in enumerate(bearings):
        data = results[bearing]["data"]
        out = results[bearing]["score"]
        idx = data["idx"].astype(int)
        n = out["n"]
        h_end = out["h_end"]
        alarm = out["alarm_emp"]

        ax_t2, ax_h = axes[r]
        ax_t2.plot(idx, out["t2"], lw=0.55, color="C3")
        ax_t2.axhline(out["ucl_emp"], color="k", ls="--", lw=0.8)
        ax_t2.axvspan(0, h_end, color="green", alpha=0.10)
        if alarm >= 0:
            ax_t2.axvline(alarm, color="red", lw=0.9)
        ax_t2.set_yscale("log")
        ax_t2.set_title(f"{bearing} T2")
        ax_t2.set_ylabel("T2")
        ax_t2.grid(alpha=0.25)

        ax_h.plot(idx, out["health"], lw=0.55, color="C0")
        ax_h.axvspan(0, h_end, color="green", alpha=0.10)
        if alarm >= 0:
            ax_h.axvline(alarm, color="red", lw=0.9)
        ax_h.set_title(
            f"health | rho={out['rho_health_ttf']:.2f}, "
            f"alarm={out['alarm_life_pct']:.0f}%"
        )
        ax_h.set_ylabel("health")
        ax_h.grid(alpha=0.25)

    axes[-1, 0].set_xlabel("snapshot index")
    axes[-1, 1].set_xlabel("snapshot index")
    fig.suptitle("PRONOSTIA Learning_set - same minimal health-curve chain", fontsize=12)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "multi_bearing_health_curves.png")
    fig.savefig(path, dpi=110)
    return path


def main():
    bearings = sorted(
        name for name in os.listdir(BASE)
        if os.path.isdir(os.path.join(BASE, name)) and name.startswith("Bearing")
    )
    results = {}
    rows = []

    print("=== Step 3 multi-bearing validation ===")
    for bearing in bearings:
        print(f"processing {bearing} ...")
        data = load_or_extract_features(bearing)
        scored = score_bearing(data)
        results[bearing] = {"data": data, "score": scored}
        row = {"bearing": bearing, **scored}
        rows.append(row)
        lead_min = scored["lead_snaps"] * 10 / 60
        print(
            f"  n={scored['n']}, FAR={scored['far'] * 100:.2f}%, "
            f"Spearman={scored['rho_health_ttf']:.3f}, "
            f"alarm={scored['alarm_emp']} ({scored['alarm_life_pct']:.1f}%), "
            f"lead={lead_min:.1f} min"
        )

    summary_path = save_summary(rows)
    plot_path = save_plot(results)
    print(f"\nsaved summary -> {summary_path}")
    print(f"saved plot -> {plot_path}")


if __name__ == "__main__":
    main()
