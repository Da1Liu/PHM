"""
回归锚点: 用共享核以"静态切分"模式重跑 UCI 液压, 复现 step7 的模型对照数值,
证明重构没破坏已验证算法.

对照 step7 (全14特征, pump 泄漏): 所有模型 AUC=1.000, Spearman=0.924, FAR=1.47%.
本脚本用 phm_pipeline 的 features + BaselineModel + RegularizedCovModel 复算
PCA+T2+SPE 与正则化协方差, 应得到一致结论.
"""
import os

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from phm_pipeline.config import hydraulic_v1
from phm_pipeline.datasource import FileSource
from phm_pipeline.features import extract_vector
from phm_pipeline.model import BaselineModel, RegularizedCovModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "uci_hydraulic")


def build_matrix():
    cfg = hydraulic_v1()
    # 耦合温度 TS1/TS2 进向量 -> 作为 channels 加载; confounder temps 为空.
    src = FileSource(
        DATA_DIR,
        channels=["PS1", "PS2", "PS3", "FS1", "FS2", "EPS1", "VS1", "SE", "TS1", "TS2"],
        temps=[],
        row_filter=lambda r: r["cooler"] == 100 and r["stable"] == 0,
    )
    X, pump, names = [], [], None
    for rec in src.records():
        vec, names = extract_vector(rec, cfg.feature_specs, cfg.derived)
        X.append(vec)
        pump.append(rec.meta["pump"])
    return np.array(X), np.array(pump), names


def evaluate(X, pump, names, label):
    healthy = np.where(pump == 0)[0]
    fault = np.where(pump != 0)[0]
    tr_n = int(round(0.60 * len(healthy)))
    train_idx = healthy[:tr_n]
    calib_idx = healthy[tr_n:]
    test_idx = np.concatenate([calib_idx, fault])
    y = (pump[test_idx] != 0).astype(int)

    results = {}
    pca = BaselineModel(feature_names=names, keep=0.95).fit(X[train_idx])
    results["PCA95_T2_SPE"] = pca.score
    for lam in [0.01, 0.05]:
        reg = RegularizedCovModel(feature_names=names, lam=lam).fit(X[train_idx])
        results[f"reg_cov_lam{lam:.2f}"] = reg.score
    mu = X[train_idx].mean(axis=0)
    sd = X[train_idx].std(axis=0) + 1e-12
    var = ((X[train_idx] - mu) / sd).var(axis=0) + 1e-12
    results["diag_cov"] = lambda Xq: np.sum(((Xq - mu) / sd) ** 2 / var, axis=1)
    results["max_abs_z"] = lambda Xq: np.max(np.abs((Xq - mu) / sd), axis=1)

    print(f"\n=== {label}  (p={len(names)}) ===")
    print("model                 AUC    Spearman   FAR%   k/expl")
    for name, scorer in results.items():
        s = scorer(X)
        ucl = np.quantile(s[calib_idx], 0.99)
        far = float(np.mean(s[calib_idx] > ucl) * 100)
        auc = roc_auc_score(y, s[test_idx])
        rho, _ = spearmanr(s[test_idx], pump[test_idx])
        extra = f"k={pca.W.shape[1]}/{pca.pca_explained:.3f}" if name == "PCA95_T2_SPE" else ""
        print(f"{name:20s}  {auc:.3f}   {rho:.3f}     {far:.2f}   {extra}")


def main():
    X, pump, names = build_matrix()
    print(f"features={len(names)} {names}")
    print(f"samples: pump0={np.sum(pump==0)} pump1={np.sum(pump==1)} pump2={np.sum(pump==2)}")

    # 全特征 (易区分, 对照 step7: 各模型 AUC=1.000, Spearman=0.924, FAR=1.47%)
    evaluate(X, pump, names, "full features (anchor vs step7)")

    # 剔除强单变量 (sep>10: q_over_p/fs1_mean/se_mean/ps3_mean), 对照 step8:
    # PCA+T2+SPE AUC~1.0, diagonal~0.747, max_abs_z~0.681.
    strong = {"q_over_p", "fs1_mean", "se_mean", "ps3_mean"}
    keep_cols = [i for i, n in enumerate(names) if n not in strong]
    names_w = [names[i] for i in keep_cols]
    evaluate(X[:, keep_cols], pump, names_w, "weak features ablation (anchor vs step8)")


if __name__ == "__main__":
    main()
