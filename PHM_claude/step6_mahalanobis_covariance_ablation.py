"""
Step 6: Mahalanobis covariance ablation.

This experiment isolates the value of the full covariance matrix in the
already validated PRONOSTIA health-curve chain. It reuses generated feature
CSVs from Step 3 and compares single-feature, Euclidean, diagonal covariance,
full covariance, regularized covariance, and shuffled-correlation controls.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import spearmanr


ROOT = os.path.dirname(__file__)
FEATURE_DIR = os.path.join(ROOT, "outputs", "step3_multi_bearing")
OUT_DIR = os.path.join(ROOT, "outputs", "step6_mahalanobis_covariance")
os.makedirs(OUT_DIR, exist_ok=True)

FEATURES_4H = ["rms_h", "kurt_h", "crest_h", "p2p_h"]
HEALTH_FRAC = 0.10
K_CONSECUTIVE = 5
RNG_SEED = 20260603


def first_consecutive_alarm(values, threshold, k):
    run = 0
    for i, above in enumerate(values > threshold):
        run = run + 1 if above else 0
        if run >= k:
            return i - k + 1
    return -1


def safe_condition_number(cov):
    eig = np.linalg.eigvalsh(cov)
    min_pos = np.min(np.abs(eig)) + 1e-12
    return float(np.max(np.abs(eig)) / min_pos), eig


def covariance_diagnostics(bearing, Z_h, feature_names):
    cov = np.cov(Z_h, rowvar=False)
    corr = np.corrcoef(Z_h, rowvar=False)
    cond, eig = safe_condition_number(cov)
    offdiag = corr[~np.eye(corr.shape[0], dtype=bool)]
    row = {
        "bearing": bearing,
        "feature_set": "|".join(feature_names),
        "condition_number": cond,
        "min_eigenvalue": float(np.min(eig)),
        "max_eigenvalue": float(np.max(eig)),
        "offdiag_abs_mean": float(np.mean(np.abs(offdiag))),
        "offdiag_abs_max": float(np.max(np.abs(offdiag))),
        "corr_rms_p2p": float(corr[0, 3]) if len(feature_names) >= 4 else np.nan,
        "corr_kurt_crest": float(corr[1, 2]) if len(feature_names) >= 3 else np.nan,
    }
    return row, corr


def score_from_cov(Z, Z_h, cov):
    mu = Z_h.mean(axis=0)
    cov_inv = np.linalg.pinv(cov)
    d = Z - mu
    return np.einsum("ij,jk,ik->i", d, cov_inv, d)


def score_models(Z, h_end, rng):
    Z_h = Z[:h_end]
    p = Z.shape[1]
    cov_full = np.cov(Z_h, rowvar=False)
    diag = np.diag(np.diag(cov_full) + 1e-12)

    shuffled = Z_h.copy()
    for j in range(p):
        shuffled[:, j] = rng.permutation(shuffled[:, j])
    cov_shuffle = np.cov(shuffled, rowvar=False)

    scores = {
        "M0_max_abs_z": np.max(np.abs(Z), axis=1),
        "M0_mean_z2": np.mean(Z**2, axis=1),
        "M1_euclidean_z2": np.sum(Z**2, axis=1),
        "M2_diag_cov": score_from_cov(Z, Z_h, diag),
        "M3_full_cov": score_from_cov(Z, Z_h, cov_full),
        "M5_shuffle_cov": score_from_cov(Z, Z_h, cov_shuffle),
    }

    for lam in [0.01, 0.05, 0.10]:
        cov_reg = (1.0 - lam) * cov_full + lam * np.eye(p)
        scores[f"M4_reg_cov_lam{lam:.2f}"] = score_from_cov(Z, Z_h, cov_reg)

    return scores


def evaluate_score(bearing, model, score, idx, h_end):
    n = len(idx)
    ucl = np.quantile(score[:h_end], 0.99)
    health = np.exp(-3.0 * score / (ucl + 1e-12))
    alarm = first_consecutive_alarm(score, ucl, K_CONSECUTIVE)
    far = np.mean(score[:h_end] > ucl)

    deg_slice = slice(h_end, n)
    time_to_fail = (n - 1) - idx[deg_slice]
    rho, _ = spearmanr(health[deg_slice], time_to_fail)
    h_deg = health[h_end:]
    roughness = float(np.mean(np.abs(np.diff(h_deg))))
    diff_p95 = float(np.quantile(np.abs(np.diff(h_deg)), 0.95))

    return {
        "bearing": bearing,
        "model": model,
        "n": n,
        "h_end": h_end,
        "far_pct": float(far * 100),
        "spearman_health_ttf": float(rho),
        "alarm_idx": int(alarm),
        "alarm_life_pct": float(100 * alarm / n) if alarm >= 0 else np.nan,
        "lead_min": float((n - alarm) * 10 / 60) if alarm >= 0 else np.nan,
        "roughness": roughness,
        "diff_p95": diff_p95,
        "ucl": float(ucl),
        "health": health,
        "score": score,
    }


def alarm_bucket(alarm_pct):
    if np.isnan(alarm_pct) or alarm_pct >= 95:
        return "too_late"
    if alarm_pct < 10:
        return "too_early"
    if alarm_pct < 40:
        return "reasonable_early"
    if alarm_pct < 75:
        return "mid_life"
    return "late"


def summarize(rows):
    models = sorted(set(row["model"] for row in rows))
    summary = []
    for model in models:
        subset = [row for row in rows if row["model"] == model]
        spearman = np.array([row["spearman_health_ttf"] for row in subset], dtype=float)
        far = np.array([row["far_pct"] for row in subset], dtype=float)
        alarm_pct = np.array([row["alarm_life_pct"] for row in subset], dtype=float)
        lead = np.array([row["lead_min"] for row in subset], dtype=float)
        rough = np.array([row["roughness"] for row in subset], dtype=float)
        buckets = [alarm_bucket(row["alarm_life_pct"]) for row in subset]

        summary.append({
            "model": model,
            "median_far_pct": float(np.nanmedian(far)),
            "median_spearman": float(np.nanmedian(spearman)),
            "mean_spearman": float(np.nanmean(spearman)),
            "median_alarm_life_pct": float(np.nanmedian(alarm_pct)),
            "median_lead_min": float(np.nanmedian(lead)),
            "median_roughness": float(np.nanmedian(rough)),
            "num_valid_alarm": int(np.sum(~np.isnan(alarm_pct))),
            "num_good_spearman": int(np.sum(spearman >= 0.5)),
            "num_too_early": buckets.count("too_early"),
            "num_too_late": buckets.count("too_late"),
        })

    # Simple pragmatic rank: reward monotonicity, penalize bad alert extremes
    # and roughness. FAR is fixed by empirical UCL for most models, so it is a
    # light tie-breaker.
    for row in summary:
        row["rank_score"] = (
            row["median_spearman"]
            - 0.05 * row["num_too_early"]
            - 0.05 * row["num_too_late"]
            - 0.2 * row["median_roughness"]
            - 0.01 * abs(row["median_far_pct"] - 1.0)
        )
    summary.sort(key=lambda r: r["rank_score"], reverse=True)
    for i, row in enumerate(summary, 1):
        row["overall_rank"] = i
    return summary


def write_csv(path, rows, columns):
    lines = [",".join(columns)]
    for row in rows:
        vals = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, float):
                vals.append(f"{value:.6f}")
            else:
                vals.append(str(value))
        lines.append(",".join(vals))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")


def save_delta(rows):
    bearings = sorted(set(row["bearing"] for row in rows))
    lookup = {(row["bearing"], row["model"]): row for row in rows}
    delta_rows = []
    for bearing in bearings:
        diag = lookup[(bearing, "M2_diag_cov")]
        full = lookup[(bearing, "M3_full_cov")]
        for reg_model in ["M4_reg_cov_lam0.01", "M4_reg_cov_lam0.05", "M4_reg_cov_lam0.10"]:
            reg = lookup[(bearing, reg_model)]
            delta_rows.append({
                "bearing": bearing,
                "comparison": f"{reg_model}_minus_diag",
                "delta_spearman": reg["spearman_health_ttf"] - diag["spearman_health_ttf"],
                "delta_alarm_life_pct": reg["alarm_life_pct"] - diag["alarm_life_pct"],
                "delta_roughness": reg["roughness"] - diag["roughness"],
            })
        delta_rows.append({
            "bearing": bearing,
            "comparison": "full_minus_diag",
            "delta_spearman": full["spearman_health_ttf"] - diag["spearman_health_ttf"],
            "delta_alarm_life_pct": full["alarm_life_pct"] - diag["alarm_life_pct"],
            "delta_roughness": full["roughness"] - diag["roughness"],
        })
    path = os.path.join(OUT_DIR, "full_vs_diag_delta.csv")
    write_csv(path, delta_rows, [
        "bearing", "comparison", "delta_spearman",
        "delta_alarm_life_pct", "delta_roughness",
    ])
    return path


def save_plot(rows, summary, corr_by_bearing):
    models = [row["model"] for row in summary]
    bearings = sorted(set(row["bearing"] for row in rows))
    lookup = {(row["bearing"], row["model"]): row for row in rows}

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    ax = axes[0, 0]
    data = [[lookup[(b, m)]["spearman_health_ttf"] for b in bearings] for m in models]
    ax.boxplot(data, tick_labels=models, vert=True)
    ax.set_ylabel("Spearman(health, TTF)")
    ax.set_title("Monotonicity across bearings")
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    ax.grid(alpha=0.25)

    ax = axes[0, 1]
    data = [[lookup[(b, m)]["alarm_life_pct"] for b in bearings] for m in models]
    ax.boxplot(data, tick_labels=models, vert=True)
    ax.set_ylabel("Alarm life pct")
    ax.set_title("First alarm timing")
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1, 0]
    b = "Bearing1_1"
    for model in ["M2_diag_cov", "M3_full_cov", "M4_reg_cov_lam0.05", "M5_shuffle_cov"]:
        row = lookup[(b, model)]
        ax.plot(row["health"], lw=0.65, label=f"{model} rho={row['spearman_health_ttf']:.2f}")
    ax.set_ylabel("health")
    ax.set_xlabel("snapshot index")
    ax.set_title("Bearing1_1 health curves")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1, 1]
    corr = corr_by_bearing["Bearing1_1"]
    im = ax.imshow(corr, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(FEATURES_4H)), FEATURES_4H, rotation=45, ha="right")
    ax.set_yticks(range(len(FEATURES_4H)), FEATURES_4H)
    ax.set_title("Bearing1_1 baseline correlation")
    for i in range(corr.shape[0]):
        for j in range(corr.shape[1]):
            ax.text(j, i, f"{corr[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "mahalanobis_covariance_ablation.png")
    fig.savefig(path, dpi=120)
    return path


def main():
    rng = np.random.default_rng(RNG_SEED)
    bearings = sorted(
        name.replace("_features.csv", "")
        for name in os.listdir(FEATURE_DIR)
        if name.startswith("Bearing") and name.endswith("_features.csv")
    )

    eval_rows = []
    diag_rows = []
    corr_by_bearing = {}
    print("=== Step 6 Mahalanobis covariance ablation ===")
    print("feature set:", ", ".join(FEATURES_4H))
    print(f"health_frac={HEALTH_FRAC}, K={K_CONSECUTIVE}")

    for bearing in bearings:
        path = os.path.join(FEATURE_DIR, f"{bearing}_features.csv")
        data = np.genfromtxt(path, delimiter=",", names=True)
        idx = data["idx"].astype(int)
        X = np.column_stack([data[name] for name in FEATURES_4H])
        n = len(idx)
        h_end = int(HEALTH_FRAC * n)
        X_h = X[:h_end]
        Z = (X - X_h.mean(axis=0)) / (X_h.std(axis=0) + 1e-12)
        Z_h = Z[:h_end]

        diag, corr = covariance_diagnostics(bearing, Z_h, FEATURES_4H)
        diag["n"] = n
        diag["h_end"] = h_end
        diag_rows.append(diag)
        corr_by_bearing[bearing] = corr

        scores = score_models(Z, h_end, rng)
        print(
            f"{bearing}: n={n}, cond={diag['condition_number']:.1f}, "
            f"offdiag_mean={diag['offdiag_abs_mean']:.3f}"
        )
        for model, score in scores.items():
            row = evaluate_score(bearing, model, score, idx, h_end)
            eval_rows.append(row)

    summary_rows = summarize(eval_rows)

    diag_path = os.path.join(OUT_DIR, "covariance_diagnostics.csv")
    write_csv(diag_path, diag_rows, [
        "bearing", "n", "h_end", "feature_set", "condition_number",
        "min_eigenvalue", "max_eigenvalue", "offdiag_abs_mean",
        "offdiag_abs_max", "corr_rms_p2p", "corr_kurt_crest",
    ])

    by_bearing_path = os.path.join(OUT_DIR, "model_comparison_by_bearing.csv")
    write_csv(by_bearing_path, eval_rows, [
        "bearing", "model", "n", "h_end", "far_pct", "spearman_health_ttf",
        "alarm_idx", "alarm_life_pct", "lead_min", "roughness", "diff_p95", "ucl",
    ])

    summary_path = os.path.join(OUT_DIR, "model_comparison_summary.csv")
    write_csv(summary_path, summary_rows, [
        "model", "median_far_pct", "median_spearman", "mean_spearman",
        "median_alarm_life_pct", "median_lead_min", "median_roughness",
        "num_valid_alarm", "num_good_spearman", "num_too_early",
        "num_too_late", "rank_score", "overall_rank",
    ])

    delta_path = save_delta(eval_rows)
    plot_path = save_plot(eval_rows, summary_rows, corr_by_bearing)

    print("\n=== model summary ===")
    for row in summary_rows:
        print(
            f"#{row['overall_rank']} {row['model']}: "
            f"median_spearman={row['median_spearman']:.3f}, "
            f"median_alarm={row['median_alarm_life_pct']:.1f}%, "
            f"good_spearman={row['num_good_spearman']}/6, "
            f"too_early={row['num_too_early']}, too_late={row['num_too_late']}"
        )

    print(f"\nsaved diagnostics -> {diag_path}")
    print(f"saved by-bearing -> {by_bearing_path}")
    print(f"saved summary -> {summary_path}")
    print(f"saved delta -> {delta_path}")
    print(f"saved plot -> {plot_path}")


if __name__ == "__main__":
    main()

