"""
Step 7: multisensor covariance health-baseline validation.

Current scope: stop point 1 only.
Extract cycle-level multisensor features from UCI Hydraulic, filter the
controlled pump-leakage subset, and report feature distributions plus healthy
baseline correlation/covariance diagnostics.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score


ROOT = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT, "data", "uci_hydraulic")
OUT_DIR = os.path.join(ROOT, "outputs", "step7_multisensor_covariance")
os.makedirs(OUT_DIR, exist_ok=True)

STEADY_START = 0.20
STEADY_END = 0.90
TARGET_FILTER = "cooler=100 AND stable=0"


FEATURE_SPECS = [
    ("PS1", "ps1_mean", "mean"),
    ("PS1", "ps1_std", "std"),
    ("PS2", "ps2_mean", "mean"),
    ("PS3", "ps3_mean", "mean"),
    ("FS1", "fs1_mean", "mean"),
    ("FS2", "fs2_mean", "mean"),
    ("EPS1", "eps1_mean", "mean"),
    ("EPS1", "eps1_std", "std"),
    ("VS1", "vs1_mean", "mean"),
    ("VS1", "vs1_std", "std"),
    ("TS1", "ts1_mean", "mean"),
    ("TS2", "ts2_mean", "mean"),
    ("SE", "se_mean", "mean"),
]

DERIVED_FEATURES = ["q_over_p"]
FEATURE_NAMES = [spec[1] for spec in FEATURE_SPECS] + DERIVED_FEATURES
RNG_SEED = 20260603


def steady_slice(n_cols):
    start = int(round(STEADY_START * n_cols))
    end = int(round(STEADY_END * n_cols))
    return slice(start, max(start + 1, end))


def load_sensor(sensor):
    path = os.path.join(DATA_DIR, f"{sensor}.txt")
    return np.loadtxt(path)


def reduce_sensor(data, reducer):
    seg = data[:, steady_slice(data.shape[1])]
    if reducer == "mean":
        return seg.mean(axis=1)
    if reducer == "std":
        return seg.std(axis=1)
    if reducer == "min":
        return seg.min(axis=1)
    if reducer == "max":
        return seg.max(axis=1)
    raise ValueError(reducer)


def extract_features():
    profile = np.loadtxt(os.path.join(DATA_DIR, "profile.txt"), dtype=int)
    rows = {
        "cycle": np.arange(len(profile), dtype=int),
        "cooler": profile[:, 0],
        "valve": profile[:, 1],
        "pump": profile[:, 2],
        "accumulator": profile[:, 3],
        "stable": profile[:, 4],
    }

    cache = {}
    for sensor, name, reducer in FEATURE_SPECS:
        if sensor not in cache:
            print(f"loading {sensor}.txt ...")
            cache[sensor] = load_sensor(sensor)
        rows[name] = reduce_sensor(cache[sensor], reducer)

    rows["q_over_p"] = rows["fs1_mean"] / (rows["ps1_mean"] + 1e-12)
    return rows


def as_matrix(rows, columns):
    return np.column_stack([rows[col] for col in columns])


def write_csv(path, rows, columns):
    n = len(rows[columns[0]])
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(columns) + "\n")
        for i in range(n):
            vals = []
            for col in columns:
                value = rows[col][i]
                if isinstance(value, (np.floating, float)):
                    vals.append(f"{float(value):.10g}")
                else:
                    vals.append(str(int(value)))
            f.write(",".join(vals) + "\n")


def summarize_by_pump(rows, mask):
    out_rows = []
    for pump in sorted(np.unique(rows["pump"][mask])):
        pmask = mask & (rows["pump"] == pump)
        for feature in FEATURE_NAMES:
            x = rows[feature][pmask]
            out_rows.append({
                "pump": int(pump),
                "feature": feature,
                "n": int(len(x)),
                "mean": float(np.mean(x)),
                "std": float(np.std(x)),
                "median": float(np.median(x)),
                "p05": float(np.quantile(x, 0.05)),
                "p95": float(np.quantile(x, 0.95)),
            })
    return out_rows


def write_dict_csv(path, dict_rows, columns):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(columns) + "\n")
        for row in dict_rows:
            vals = []
            for col in columns:
                value = row[col]
                if isinstance(value, float):
                    vals.append(f"{value:.10g}")
                else:
                    vals.append(str(value))
            f.write(",".join(vals) + "\n")


def standardized_healthy(rows, healthy_mask):
    X = as_matrix(rows, FEATURE_NAMES)
    Xh = X[healthy_mask]
    mu = Xh.mean(axis=0)
    sd = Xh.std(axis=0) + 1e-12
    return (X - mu) / sd, mu, sd


def covariance_diagnostics(Z_h):
    corr = np.corrcoef(Z_h, rowvar=False)
    cov = np.cov(Z_h, rowvar=False)
    eig = np.linalg.eigvalsh(cov)
    offdiag = corr[~np.eye(corr.shape[0], dtype=bool)]
    return {
        "n_healthy": int(len(Z_h)),
        "feature_count": int(Z_h.shape[1]),
        "condition_number": float(np.max(np.abs(eig)) / (np.min(np.abs(eig)) + 1e-12)),
        "min_eigenvalue": float(np.min(eig)),
        "max_eigenvalue": float(np.max(eig)),
        "offdiag_abs_mean": float(np.mean(np.abs(offdiag))),
        "offdiag_abs_max": float(np.max(np.abs(offdiag))),
    }, corr


def first_consecutive_alarm(values, threshold, k=5):
    run = 0
    for i, above in enumerate(values > threshold):
        run = run + 1 if above else 0
        if run >= k:
            return i - k + 1
    return -1


def fit_standardizer(X_train):
    mu = X_train.mean(axis=0)
    sd = X_train.std(axis=0) + 1e-12
    return mu, sd


def standardize(X, mu, sd):
    return (X - mu) / sd


def score_from_cov(Z, Z_train, cov):
    mu = Z_train.mean(axis=0)
    inv = np.linalg.pinv(cov)
    d = Z - mu
    return np.einsum("ij,jk,ik->i", d, inv, d)


def pca_scores(Z_train, Z, keep=0.95, include_spe=False):
    _, s, vt = np.linalg.svd(Z_train, full_matrices=False)
    eig = (s**2) / max(len(Z_train) - 1, 1)
    ratio = eig / (eig.sum() + 1e-12)
    k = int(np.searchsorted(np.cumsum(ratio), keep) + 1)
    W = vt[:k].T
    lam = eig[:k] + 1e-12
    Z_proj = Z @ W
    t2 = np.sum((Z_proj**2) / lam, axis=1)
    if not include_spe:
        return t2, {"pca_k": k, "pca_explained": float(ratio[:k].sum())}

    Z_train_proj = Z_train @ W
    t2_train = np.sum((Z_train_proj**2) / lam, axis=1)
    residual = Z - Z_proj @ W.T
    spe = np.sum(residual**2, axis=1)
    residual_train = Z_train - Z_train_proj @ W.T
    spe_train = np.sum(residual_train**2, axis=1)
    t2_scale = np.quantile(t2_train, 0.99) + 1e-12
    spe_scale = np.quantile(spe_train, 0.99) + 1e-12
    score = np.maximum(t2 / t2_scale, spe / spe_scale)
    return score, {"pca_k": k, "pca_explained": float(ratio[:k].sum())}


def split_for_model(rows, subset_mask):
    healthy_idx = np.where(subset_mask & (rows["pump"] == 0))[0]
    fault_idx = np.where(subset_mask & (rows["pump"] != 0))[0]
    train_n = int(round(0.60 * len(healthy_idx)))
    train_idx = healthy_idx[:train_n]
    calib_idx = healthy_idx[train_n:]
    test_idx = np.concatenate([calib_idx, fault_idx])
    return train_idx, calib_idx, test_idx


def score_all_models(rows, subset_mask):
    rng = np.random.default_rng(RNG_SEED)
    X = as_matrix(rows, FEATURE_NAMES)
    train_idx, calib_idx, test_idx = split_for_model(rows, subset_mask)
    mu, sd = fit_standardizer(X[train_idx])
    Z = standardize(X, mu, sd)
    Z_train = Z[train_idx]
    cov_full = np.cov(Z_train, rowvar=False)
    cov_diag = np.diag(np.diag(cov_full) + 1e-12)

    shuffled = Z_train.copy()
    for j in range(shuffled.shape[1]):
        shuffled[:, j] = rng.permutation(shuffled[:, j])
    cov_shuffle = np.cov(shuffled, rowvar=False)

    model_scores = {
        "M0_max_abs_z": np.max(np.abs(Z), axis=1),
        "M1_diag_cov": score_from_cov(Z, Z_train, cov_diag),
        "M2_full_cov_pinv": score_from_cov(Z, Z_train, cov_full),
        "M6_shuffle_cov": score_from_cov(Z, Z_train, cov_shuffle),
    }
    for lam in [0.01, 0.05, 0.10, 0.20]:
        cov_reg = (1.0 - lam) * cov_full + lam * np.eye(cov_full.shape[0])
        model_scores[f"M3_reg_cov_lam{lam:.2f}"] = score_from_cov(Z, Z_train, cov_reg)

    pca_t2, pca_info = pca_scores(Z_train, Z, keep=0.95, include_spe=False)
    pca_spe, pca_spe_info = pca_scores(Z_train, Z, keep=0.95, include_spe=True)
    model_scores["M4_pca95_t2"] = pca_t2
    model_scores["M5_pca95_t2_spe"] = pca_spe
    extras = {
        "M4_pca95_t2": pca_info,
        "M5_pca95_t2_spe": pca_spe_info,
    }

    rows_out = []
    score_rows = []
    y_fault = (rows["pump"][test_idx] != 0).astype(int)
    pump_test = rows["pump"][test_idx]
    for model, score in model_scores.items():
        ucl = np.quantile(score[calib_idx], 0.99)
        far = np.mean(score[calib_idx] > ucl)
        auc = roc_auc_score(y_fault, score[test_idx])
        rho, _ = spearmanr(score[test_idx], pump_test)
        means = {
            f"mean_score_pump{pump}": float(np.mean(score[test_idx][pump_test == pump]))
            for pump in sorted(np.unique(pump_test))
        }
        first_alarm = first_consecutive_alarm(score[test_idx], ucl)
        row = {
            "model": model,
            "train_n": int(len(train_idx)),
            "calib_n": int(len(calib_idx)),
            "test_n": int(len(test_idx)),
            "feature_count": int(X.shape[1]),
            "ucl": float(ucl),
            "far_calibration_pct": float(far * 100),
            "auc_fault_vs_healthy": float(auc),
            "spearman_score_pump": float(rho),
            "first_alarm_test_idx": int(first_alarm),
            "pca_k": extras.get(model, {}).get("pca_k", ""),
            "pca_explained": extras.get(model, {}).get("pca_explained", ""),
            **means,
        }
        rows_out.append(row)
        for idx in test_idx:
            score_rows.append({
                "cycle": int(rows["cycle"][idx]),
                "pump": int(rows["pump"][idx]),
                "model": model,
                "score": float(score[idx]),
                "ucl": float(ucl),
                "health": float(np.exp(-3.0 * score[idx] / (ucl + 1e-12))),
                "is_alarm": int(score[idx] > ucl),
            })

    return rows_out, score_rows


def save_model_plot(score_rows, summary_rows):
    preferred = [
        "M0_max_abs_z",
        "M1_diag_cov",
        "M2_full_cov_pinv",
        "M3_reg_cov_lam0.05",
        "M4_pca95_t2",
        "M5_pca95_t2_spe",
        "M6_shuffle_cov",
    ]
    score_by_model = {m: [] for m in preferred}
    pump_by_model = {m: [] for m in preferred}
    for row in score_rows:
        if row["model"] in score_by_model:
            score_by_model[row["model"]].append(row["score"] / (row["ucl"] + 1e-12))
            pump_by_model[row["model"]].append(row["pump"])

    fig, axes = plt.subplots(2, 1, figsize=(13, 9))
    ax = axes[0]
    models = [row["model"] for row in summary_rows]
    auc = [row["auc_fault_vs_healthy"] for row in summary_rows]
    rho = [row["spearman_score_pump"] for row in summary_rows]
    x = np.arange(len(models))
    ax.bar(x - 0.18, auc, width=0.36, label="AUC")
    ax.bar(x + 0.18, rho, width=0.36, label="Spearman")
    ax.set_xticks(x, models, rotation=40, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_title("Model comparison on pump leakage subset")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)

    ax = axes[1]
    for model in preferred:
        vals = np.asarray(score_by_model[model])
        pumps = np.asarray(pump_by_model[model])
        if len(vals) == 0:
            continue
        med = [np.median(vals[pumps == pump]) for pump in [0, 1, 2]]
        ax.plot([0, 1, 2], med, marker="o", label=model)
    ax.set_yscale("log")
    ax.set_xlabel("pump leakage level")
    ax.set_ylabel("median score / UCL")
    ax.set_title("Score severity by pump level")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "model_comparison.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def save_corr_csv(path, corr):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("feature," + ",".join(FEATURE_NAMES) + "\n")
        for name, row in zip(FEATURE_NAMES, corr):
            f.write(name + "," + ",".join(f"{v:.8f}" for v in row) + "\n")


def save_plots(rows, subset_mask, corr):
    pumps = sorted(np.unique(rows["pump"][subset_mask]))
    fig, axes = plt.subplots(4, 4, figsize=(16, 12))
    axes = axes.ravel()
    for ax, feature in zip(axes, FEATURE_NAMES):
        data = [rows[feature][subset_mask & (rows["pump"] == pump)] for pump in pumps]
        ax.boxplot(data, tick_labels=[str(p) for p in pumps], showfliers=False)
        ax.set_title(feature, fontsize=9)
        ax.set_xlabel("pump")
        ax.grid(alpha=0.25)
    for ax in axes[len(FEATURE_NAMES):]:
        ax.axis("off")
    fig.suptitle("Multisensor feature distributions by pump leakage level", fontsize=13)
    fig.tight_layout()
    feature_plot = os.path.join(OUT_DIR, "feature_distributions_by_pump.png")
    fig.savefig(feature_plot, dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(corr, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(FEATURE_NAMES)), FEATURE_NAMES, rotation=45, ha="right")
    ax.set_yticks(range(len(FEATURE_NAMES)), FEATURE_NAMES)
    ax.set_title("Healthy baseline correlation matrix, pump=0")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    corr_plot = os.path.join(OUT_DIR, "healthy_correlation_heatmap.png")
    fig.savefig(corr_plot, dpi=120)
    plt.close(fig)
    return feature_plot, corr_plot


def main():
    print("=== Step 7 stop point 1: multisensor feature self-check ===")
    print("dataset: UCI Hydraulic")
    print("subset:", TARGET_FILTER)
    rows = extract_features()

    all_columns = [
        "cycle", "cooler", "valve", "pump", "accumulator", "stable",
        *FEATURE_NAMES,
    ]
    features_path = os.path.join(OUT_DIR, "features_multisensor.csv")
    write_csv(features_path, rows, all_columns)

    subset_mask = (rows["cooler"] == 100) & (rows["stable"] == 0)
    healthy_mask = subset_mask & (rows["pump"] == 0)
    counts = {
        int(p): int(np.sum(subset_mask & (rows["pump"] == p)))
        for p in sorted(np.unique(rows["pump"][subset_mask]))
    }

    summary_rows = summarize_by_pump(rows, subset_mask)
    summary_path = os.path.join(OUT_DIR, "feature_summary_by_pump.csv")
    write_dict_csv(summary_path, summary_rows, [
        "pump", "feature", "n", "mean", "std", "median", "p05", "p95",
    ])

    Z, _, _ = standardized_healthy(rows, healthy_mask)
    Z_h = Z[healthy_mask]
    diag, corr = covariance_diagnostics(Z_h)
    diag["subset"] = TARGET_FILTER
    diag_path = os.path.join(OUT_DIR, "covariance_diagnostics.csv")
    write_dict_csv(diag_path, [diag], [
        "subset", "n_healthy", "feature_count", "condition_number",
        "min_eigenvalue", "max_eigenvalue", "offdiag_abs_mean",
        "offdiag_abs_max",
    ])

    corr_path = os.path.join(OUT_DIR, "healthy_correlation_matrix.csv")
    save_corr_csv(corr_path, corr)
    feature_plot, corr_plot = save_plots(rows, subset_mask, corr)

    model_rows, score_rows = score_all_models(rows, subset_mask)
    model_rows.sort(
        key=lambda r: (
            r["auc_fault_vs_healthy"],
            r["spearman_score_pump"],
            -r["far_calibration_pct"],
        ),
        reverse=True,
    )
    model_summary_path = os.path.join(OUT_DIR, "model_summary.csv")
    model_columns = [
        "model", "train_n", "calib_n", "test_n", "feature_count", "ucl",
        "far_calibration_pct", "auc_fault_vs_healthy", "spearman_score_pump",
        "mean_score_pump0", "mean_score_pump1", "mean_score_pump2",
        "first_alarm_test_idx", "pca_k", "pca_explained",
    ]
    write_dict_csv(model_summary_path, model_rows, model_columns)
    score_path = os.path.join(OUT_DIR, "model_scores.csv")
    write_dict_csv(score_path, score_rows, [
        "cycle", "pump", "model", "score", "ucl", "health", "is_alarm",
    ])
    model_plot = save_model_plot(score_rows, model_rows)

    print("\nsubset counts by pump:", counts)
    print("healthy baseline samples:", int(np.sum(healthy_mask)))
    print(
        "covariance diagnostics: "
        f"features={diag['feature_count']}, "
        f"cond={diag['condition_number']:.1f}, "
        f"offdiag_abs_mean={diag['offdiag_abs_mean']:.3f}, "
        f"offdiag_abs_max={diag['offdiag_abs_max']:.3f}"
    )
    print(f"\nsaved features -> {features_path}")
    print(f"saved feature summary -> {summary_path}")
    print(f"saved covariance diagnostics -> {diag_path}")
    print(f"saved correlation matrix -> {corr_path}")
    print(f"saved feature plot -> {feature_plot}")
    print(f"saved correlation plot -> {corr_plot}")
    print(f"saved model summary -> {model_summary_path}")
    print(f"saved model scores -> {score_path}")
    print(f"saved model plot -> {model_plot}")

    print("\n=== stop point 2 model summary ===")
    for row in model_rows:
        pca = ""
        if row["pca_k"] != "":
            pca = f", k={row['pca_k']}, explained={row['pca_explained']:.3f}"
        print(
            f"{row['model']}: AUC={row['auc_fault_vs_healthy']:.3f}, "
            f"Spearman={row['spearman_score_pump']:.3f}, "
            f"FAR={row['far_calibration_pct']:.2f}%, "
            f"mean0/1/2={row['mean_score_pump0']:.3g}/"
            f"{row['mean_score_pump1']:.3g}/{row['mean_score_pump2']:.3g}"
            f"{pca}"
        )


if __name__ == "__main__":
    main()
