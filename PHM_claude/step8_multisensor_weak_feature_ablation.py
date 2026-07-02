"""
Step 8: remove strongly separable single-variable features and rerun
multisensor covariance model comparisons.

Purpose:
UCI pump leakage is too easy with features such as q_over_p and fs1_mean.
This script removes features with strong univariate separation and checks
whether covariance/PCA models still add value on weaker marginal features.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score


ROOT = os.path.dirname(__file__)
IN_PATH = os.path.join(ROOT, "outputs", "step7_multisensor_covariance", "features_multisensor.csv")
OUT_DIR = os.path.join(ROOT, "outputs", "step8_multisensor_weak_features")
os.makedirs(OUT_DIR, exist_ok=True)

FEATURE_NAMES = [
    "ps1_mean", "ps1_std", "ps2_mean", "ps3_mean",
    "fs1_mean", "fs2_mean", "eps1_mean", "eps1_std",
    "vs1_mean", "vs1_std", "ts1_mean", "ts2_mean",
    "se_mean", "q_over_p",
]
RNG_SEED = 20260603


def split_indices(df):
    subset = df[(df["cooler"] == 100) & (df["stable"] == 0)].copy()
    healthy = subset[subset["pump"] == 0].index.to_numpy()
    fault = subset[subset["pump"] != 0].index.to_numpy()
    train_n = int(round(0.60 * len(healthy)))
    train_idx = healthy[:train_n]
    calib_idx = healthy[train_n:]
    test_idx = np.concatenate([calib_idx, fault])
    return subset.index.to_numpy(), train_idx, calib_idx, test_idx


def separation_table(df, subset_idx):
    rows = []
    sub = df.loc[subset_idx]
    for feature in FEATURE_NAMES:
        x0 = sub[sub["pump"] == 0][feature].to_numpy(float)
        x2 = sub[sub["pump"] == 2][feature].to_numpy(float)
        sep = abs(x2.mean() - x0.mean()) / ((((x0.std() ** 2) + (x2.std() ** 2)) / 2) ** 0.5 + 1e-12)
        rows.append({
            "feature": feature,
            "mean_pump0": float(x0.mean()),
            "mean_pump2": float(x2.mean()),
            "delta_0_to_2": float(x2.mean() - x0.mean()),
            "sep_0_vs_2": float(sep),
        })
    rows.sort(key=lambda r: r["sep_0_vs_2"], reverse=True)
    return rows


def standardize(X, train_rows):
    mu = X[train_rows].mean(axis=0)
    sd = X[train_rows].std(axis=0) + 1e-12
    return (X - mu) / sd


def score_cov(Z, train_rows, cov):
    Zt = Z[train_rows]
    mu = Zt.mean(axis=0)
    inv = np.linalg.pinv(cov)
    d = Z - mu
    return np.einsum("ij,jk,ik->i", d, inv, d)


def score_pca(Z, train_rows, keep=0.95, include_spe=False):
    Zt = Z[train_rows]
    _, s, vt = np.linalg.svd(Zt, full_matrices=False)
    eig = (s**2) / max(len(Zt) - 1, 1)
    ratio = eig / (eig.sum() + 1e-12)
    k = int(np.searchsorted(np.cumsum(ratio), keep) + 1)
    W = vt[:k].T
    lam = eig[:k] + 1e-12
    proj = Z @ W
    t2 = np.sum((proj**2) / lam, axis=1)
    if not include_spe:
        return t2, {"pca_k": k, "pca_explained": float(ratio[:k].sum())}
    train_proj = Zt @ W
    t2_train = np.sum((train_proj**2) / lam, axis=1)
    resid = Z - proj @ W.T
    resid_train = Zt - train_proj @ W.T
    spe = np.sum(resid**2, axis=1)
    spe_train = np.sum(resid_train**2, axis=1)
    score = np.maximum(
        t2 / (np.quantile(t2_train, 0.99) + 1e-12),
        spe / (np.quantile(spe_train, 0.99) + 1e-12),
    )
    return score, {"pca_k": k, "pca_explained": float(ratio[:k].sum())}


def run_models(df, feature_set, train_idx, calib_idx, test_idx):
    rng = np.random.default_rng(RNG_SEED)
    X = df[feature_set].to_numpy(float)
    # Positional rows are dataframe index values because df is loaded with a
    # RangeIndex and not subset-reset.
    Z = standardize(X, train_idx)
    Zt = Z[train_idx]
    cov = np.cov(Zt, rowvar=False)
    diag = np.diag(np.diag(cov) + 1e-12)
    shuffled = Zt.copy()
    for j in range(shuffled.shape[1]):
        shuffled[:, j] = rng.permutation(shuffled[:, j])
    cov_shuffle = np.cov(shuffled, rowvar=False)

    model_scores = {
        "M0_max_abs_z": np.max(np.abs(Z), axis=1),
        "M1_diag_cov": score_cov(Z, train_idx, diag),
        "M2_full_cov_pinv": score_cov(Z, train_idx, cov),
        "M6_shuffle_cov": score_cov(Z, train_idx, cov_shuffle),
    }
    for lam in [0.01, 0.05, 0.10, 0.20]:
        cov_reg = (1.0 - lam) * cov + lam * np.eye(len(feature_set))
        model_scores[f"M3_reg_cov_lam{lam:.2f}"] = score_cov(Z, train_idx, cov_reg)
    model_scores["M4_pca95_t2"], pca_info = score_pca(Z, train_idx, keep=0.95, include_spe=False)
    model_scores["M5_pca95_t2_spe"], pca_spe_info = score_pca(Z, train_idx, keep=0.95, include_spe=True)
    extras = {"M4_pca95_t2": pca_info, "M5_pca95_t2_spe": pca_spe_info}

    y = (df.loc[test_idx, "pump"].to_numpy() != 0).astype(int)
    pump = df.loc[test_idx, "pump"].to_numpy()
    rows = []
    for model, score in model_scores.items():
        ucl = np.quantile(score[calib_idx], 0.99)
        row = {
            "model": model,
            "feature_count": len(feature_set),
            "features": "|".join(feature_set),
            "far_calibration_pct": float(np.mean(score[calib_idx] > ucl) * 100),
            "auc_fault_vs_healthy": float(roc_auc_score(y, score[test_idx])),
            "spearman_score_pump": float(spearmanr(score[test_idx], pump)[0]),
            "mean_score_pump0": float(np.mean(score[test_idx][pump == 0])),
            "mean_score_pump1": float(np.mean(score[test_idx][pump == 1])),
            "mean_score_pump2": float(np.mean(score[test_idx][pump == 2])),
            "pca_k": extras.get(model, {}).get("pca_k", ""),
            "pca_explained": extras.get(model, {}).get("pca_explained", ""),
        }
        rows.append(row)

    eig = np.linalg.eigvalsh(cov)
    corr = np.corrcoef(Zt, rowvar=False)
    offdiag = corr[~np.eye(corr.shape[0], dtype=bool)] if len(feature_set) > 1 else np.array([0.0])
    diag_row = {
        "feature_count": len(feature_set),
        "features": "|".join(feature_set),
        "condition_number": float(np.max(np.abs(eig)) / (np.min(np.abs(eig)) + 1e-12)),
        "min_eigenvalue": float(np.min(eig)),
        "max_eigenvalue": float(np.max(eig)),
        "offdiag_abs_mean": float(np.mean(np.abs(offdiag))),
        "offdiag_abs_max": float(np.max(np.abs(offdiag))),
    }
    return rows, diag_row


def write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def save_plot(summary):
    df = pd.DataFrame(summary)
    variants = list(df["variant"].unique())
    fig, axes = plt.subplots(2, 1, figsize=(13, 9))
    for metric, ax in [("auc_fault_vs_healthy", axes[0]), ("spearman_score_pump", axes[1])]:
        pivot = df.pivot(index="model", columns="variant", values=metric)
        pivot.plot(kind="bar", ax=ax)
        ax.set_title(metric)
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="x", labelrotation=40)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "weak_feature_ablation.png")
    fig.savefig(path, dpi=120)
    return path


def main():
    print("=== Step 8 weak single-variable feature ablation ===")
    df = pd.read_csv(IN_PATH)
    subset_idx, train_idx, calib_idx, test_idx = split_indices(df)
    sep_rows = separation_table(df, subset_idx)
    sep_path = os.path.join(OUT_DIR, "feature_univariate_separation.csv")
    write_csv(sep_path, sep_rows)

    variants = {
        "all_features": FEATURE_NAMES,
        "remove_sep_gt_10": [r["feature"] for r in sep_rows if r["sep_0_vs_2"] <= 10],
        "remove_sep_gt_3": [r["feature"] for r in sep_rows if r["sep_0_vs_2"] <= 3],
        "relationship_only_manual": [
            "ps1_std", "eps1_std", "vs1_mean", "vs1_std",
            "fs2_mean", "ts1_mean", "ts2_mean",
        ],
    }

    summary = []
    diagnostics = []
    for variant, features in variants.items():
        rows, diag = run_models(df, features, train_idx, calib_idx, test_idx)
        for row in rows:
            row["variant"] = variant
        diag["variant"] = variant
        summary.extend(rows)
        diagnostics.append(diag)
        print(
            f"{variant}: features={len(features)}, "
            f"cond={diag['condition_number']:.2g}, "
            f"offdiag_mean={diag['offdiag_abs_mean']:.3f}"
        )
        best = sorted(rows, key=lambda r: (r["auc_fault_vs_healthy"], r["spearman_score_pump"]), reverse=True)[:3]
        for row in best:
            print(
                f"  {row['model']}: AUC={row['auc_fault_vs_healthy']:.3f}, "
                f"Spearman={row['spearman_score_pump']:.3f}, "
                f"FAR={row['far_calibration_pct']:.2f}%"
            )

    summary_path = os.path.join(OUT_DIR, "weak_feature_model_summary.csv")
    diag_path = os.path.join(OUT_DIR, "weak_feature_covariance_diagnostics.csv")
    write_csv(summary_path, summary)
    write_csv(diag_path, diagnostics)
    plot_path = save_plot(summary)

    print(f"\nsaved separation -> {sep_path}")
    print(f"saved summary -> {summary_path}")
    print(f"saved diagnostics -> {diag_path}")
    print(f"saved plot -> {plot_path}")


if __name__ == "__main__":
    main()

