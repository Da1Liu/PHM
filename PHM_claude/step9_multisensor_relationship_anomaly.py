"""
Step 9: relationship-anomaly test for multisensor covariance baseline.

This test creates synthetic samples whose individual feature values are drawn
from healthy calibration samples, but selected cross-sensor relationships are
broken by independently permuting feature groups. It checks whether covariance
or PCA models detect relationship violations better than single-variable or
diagonal models.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


ROOT = os.path.dirname(__file__)
FEATURE_PATH = os.path.join(ROOT, "outputs", "step7_multisensor_covariance", "features_multisensor.csv")
OUT_DIR = os.path.join(ROOT, "outputs", "step9_relationship_anomaly")
os.makedirs(OUT_DIR, exist_ok=True)

RNG_SEED = 20260603

# Use the feature set that removed the strongest univariate pump indicators
# from Step 8. This makes the test focus on cross-sensor relationships.
FEATURES = [
    "ps1_mean", "ps2_mean", "eps1_mean",
    "ps1_std", "eps1_std", "vs1_mean",
    "fs2_mean", "vs1_std", "ts1_mean", "ts2_mean",
]


def split_indices(df):
    subset = df[(df["cooler"] == 100) & (df["stable"] == 0)].copy()
    healthy = subset[subset["pump"] == 0].index.to_numpy()
    train_n = int(round(0.60 * len(healthy)))
    train_idx = healthy[:train_n]
    calib_idx = healthy[train_n:]
    return train_idx, calib_idx


def standardize(X, train_idx):
    mu = X[train_idx].mean(axis=0)
    sd = X[train_idx].std(axis=0) + 1e-12
    return (X - mu) / sd, mu, sd


def score_cov(Z, train_idx, cov):
    Zt = Z[train_idx]
    mu = Zt.mean(axis=0)
    inv = np.linalg.pinv(cov)
    d = Z - mu
    return np.einsum("ij,jk,ik->i", d, inv, d)


def pca_score(Z_train, Z, keep=0.95, include_spe=False):
    _, s, vt = np.linalg.svd(Z_train, full_matrices=False)
    eig = (s**2) / max(len(Z_train) - 1, 1)
    ratio = eig / (eig.sum() + 1e-12)
    k = int(np.searchsorted(np.cumsum(ratio), keep) + 1)
    W = vt[:k].T
    lam = eig[:k] + 1e-12
    proj = Z @ W
    t2 = np.sum((proj**2) / lam, axis=1)
    if not include_spe:
        return t2, {"pca_k": k, "pca_explained": float(ratio[:k].sum())}

    train_proj = Z_train @ W
    t2_train = np.sum((train_proj**2) / lam, axis=1)
    resid = Z - proj @ W.T
    resid_train = Z_train - train_proj @ W.T
    spe = np.sum(resid**2, axis=1)
    spe_train = np.sum(resid_train**2, axis=1)
    return np.maximum(
        t2 / (np.quantile(t2_train, 0.99) + 1e-12),
        spe / (np.quantile(spe_train, 0.99) + 1e-12),
    ), {"pca_k": k, "pca_explained": float(ratio[:k].sum())}


def build_relationship_anomalies(X_calib, rng):
    scenarios = {}

    # Scenario A: independently permute all features. This keeps every
    # feature's marginal healthy distribution but destroys most relationships.
    all_perm = X_calib.copy()
    for j in range(all_perm.shape[1]):
        all_perm[:, j] = rng.permutation(all_perm[:, j])
    scenarios["permute_all_features"] = all_perm

    # Scenario B: break power/flow/pressure relation by permuting EPS1 only.
    eps_perm = X_calib.copy()
    eps_j = FEATURES.index("eps1_mean")
    eps_std_j = FEATURES.index("eps1_std")
    eps_perm[:, eps_j] = rng.permutation(eps_perm[:, eps_j])
    eps_perm[:, eps_std_j] = rng.permutation(eps_perm[:, eps_std_j])
    scenarios["permute_power_only"] = eps_perm

    # Scenario C: break thermal relation by permuting TS1/TS2 independently.
    temp_perm = X_calib.copy()
    for name in ["ts1_mean", "ts2_mean"]:
        j = FEATURES.index(name)
        temp_perm[:, j] = rng.permutation(temp_perm[:, j])
    scenarios["permute_temperature_pair"] = temp_perm

    # Scenario D: break pressure relation by permuting PS1/PS2 independently.
    pressure_perm = X_calib.copy()
    for name in ["ps1_mean", "ps2_mean"]:
        j = FEATURES.index(name)
        pressure_perm[:, j] = rng.permutation(pressure_perm[:, j])
    scenarios["permute_pressure_pair"] = pressure_perm

    # Scenario E: block shuffle. Keeps pressure pair internally aligned and
    # temperature pair internally aligned, but breaks relationships across
    # pressure, power, flow/vibration, and temperature groups.
    groups = [
        ["ps1_mean", "ps2_mean", "ps1_std"],
        ["eps1_mean", "eps1_std"],
        ["fs2_mean", "vs1_mean", "vs1_std"],
        ["ts1_mean", "ts2_mean"],
    ]
    block_perm = X_calib.copy()
    for group in groups:
        idx = [FEATURES.index(name) for name in group]
        perm = rng.permutation(len(block_perm))
        block_perm[:, idx] = block_perm[perm][:, idx]
    scenarios["permute_sensor_blocks"] = block_perm

    return scenarios


def fit_models(X_train, X_eval, train_idx_relative):
    Z_all, _, _ = standardize(np.vstack([X_train, X_eval]), train_idx_relative)
    Z_train = Z_all[:len(X_train)]
    Z_eval = Z_all[len(X_train):]
    cov = np.cov(Z_train, rowvar=False)
    diag = np.diag(np.diag(cov) + 1e-12)
    models = {
        "M0_max_abs_z": np.max(np.abs(Z_eval), axis=1),
        "M1_diag_cov": score_cov(np.vstack([Z_train, Z_eval]), np.arange(len(Z_train)), diag)[len(Z_train):],
        "M2_full_cov_pinv": score_cov(np.vstack([Z_train, Z_eval]), np.arange(len(Z_train)), cov)[len(Z_train):],
    }
    for lam in [0.01, 0.05, 0.10, 0.20]:
        cov_reg = (1.0 - lam) * cov + lam * np.eye(cov.shape[0])
        models[f"M3_reg_cov_lam{lam:.2f}"] = score_cov(
            np.vstack([Z_train, Z_eval]), np.arange(len(Z_train)), cov_reg
        )[len(Z_train):]
    models["M4_pca95_t2"], pca_info = pca_score(Z_train, Z_eval, keep=0.95, include_spe=False)
    models["M5_pca95_t2_spe"], pca_spe_info = pca_score(Z_train, Z_eval, keep=0.95, include_spe=True)
    return models, {"M4_pca95_t2": pca_info, "M5_pca95_t2_spe": pca_spe_info}


def main():
    print("=== Step 9 multisensor relationship anomaly test ===")
    rng = np.random.default_rng(RNG_SEED)
    df = pd.read_csv(FEATURE_PATH)
    train_idx, calib_idx = split_indices(df)
    X = df[FEATURES].to_numpy(float)
    X_train = X[train_idx]
    X_calib = X[calib_idx]
    scenarios = build_relationship_anomalies(X_calib, rng)

    rows = []
    score_rows = []
    train_rel = np.arange(len(X_train))
    for scenario, X_anom in scenarios.items():
        X_eval = np.vstack([X_calib, X_anom])
        y = np.concatenate([np.zeros(len(X_calib)), np.ones(len(X_anom))])
        scores, extras = fit_models(X_train, X_eval, train_rel)
        for model, score in scores.items():
            healthy_score = score[:len(X_calib)]
            anom_score = score[len(X_calib):]
            ucl = np.quantile(healthy_score, 0.99)
            row = {
                "scenario": scenario,
                "model": model,
                "feature_count": len(FEATURES),
                "features": "|".join(FEATURES),
                "auc_relationship_anomaly": float(roc_auc_score(y, score)),
                "healthy_far_pct": float(np.mean(healthy_score > ucl) * 100),
                "anomaly_detection_pct": float(np.mean(anom_score > ucl) * 100),
                "median_healthy_score_over_ucl": float(np.median(healthy_score / (ucl + 1e-12))),
                "median_anomaly_score_over_ucl": float(np.median(anom_score / (ucl + 1e-12))),
                "pca_k": extras.get(model, {}).get("pca_k", ""),
                "pca_explained": extras.get(model, {}).get("pca_explained", ""),
            }
            rows.append(row)
            for kind, values in [("healthy", healthy_score), ("relationship_anomaly", anom_score)]:
                for v in values:
                    score_rows.append({
                        "scenario": scenario,
                        "model": model,
                        "kind": kind,
                        "score_over_ucl": float(v / (ucl + 1e-12)),
                    })

    summary = pd.DataFrame(rows)
    summary_path = os.path.join(OUT_DIR, "relationship_anomaly_summary.csv")
    summary.to_csv(summary_path, index=False)
    scores_path = os.path.join(OUT_DIR, "relationship_anomaly_scores.csv")
    pd.DataFrame(score_rows).to_csv(scores_path, index=False)

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    pivot_auc = summary.pivot(index="model", columns="scenario", values="auc_relationship_anomaly")
    pivot_auc.plot(kind="bar", ax=axes[0])
    axes[0].set_ylim(0, 1.05)
    axes[0].set_title("AUC for relationship anomaly detection")
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].tick_params(axis="x", labelrotation=40)

    pivot_det = summary.pivot(index="model", columns="scenario", values="anomaly_detection_pct")
    pivot_det.plot(kind="bar", ax=axes[1])
    axes[1].set_ylim(0, 105)
    axes[1].set_title("Detection rate at healthy 99% UCL")
    axes[1].set_ylabel("%")
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].tick_params(axis="x", labelrotation=40)
    fig.tight_layout()
    plot_path = os.path.join(OUT_DIR, "relationship_anomaly_comparison.png")
    fig.savefig(plot_path, dpi=120)

    print(f"features: {', '.join(FEATURES)}")
    for scenario in summary["scenario"].unique():
        print(f"\nscenario: {scenario}")
        top = summary[summary["scenario"] == scenario].sort_values(
            ["auc_relationship_anomaly", "anomaly_detection_pct"], ascending=False
        )
        for _, row in top.head(5).iterrows():
            print(
                f"  {row['model']}: AUC={row['auc_relationship_anomaly']:.3f}, "
                f"detect={row['anomaly_detection_pct']:.1f}%, "
                f"median_ratio={row['median_anomaly_score_over_ucl']:.2f}"
            )

    print(f"\nsaved summary -> {summary_path}")
    print(f"saved scores -> {scores_path}")
    print(f"saved plot -> {plot_path}")


if __name__ == "__main__":
    main()

