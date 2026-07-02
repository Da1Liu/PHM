"""Step 1 自检画图: Bearing1_1 四特征时间曲线 (水平+垂直)"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "step1_features")
csv_path = os.path.join(OUT_DIR, "Bearing1_1_features.csv")

data = np.genfromtxt(csv_path, delimiter=",", names=True)
idx = data["idx"]
n = len(idx)

feats = ["rms", "kurt", "crest", "p2p"]
titles = {
    "rms": "RMS (energy)",
    "kurt": "Kurtosis (impulsiveness)",
    "crest": "Crest factor",
    "p2p": "Peak-to-peak",
}

fig, axes = plt.subplots(4, 1, figsize=(11, 13), sharex=True)
for ax, f in zip(axes, feats):
    ax.plot(idx, data[f + "_h"], lw=0.7, label="horizontal", color="C0")
    ax.plot(idx, data[f + "_v"], lw=0.7, label="vertical", color="C1", alpha=0.7)
    ax.set_ylabel(titles[f])
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
axes[-1].set_xlabel("snapshot index (time ->, failure at end)")
fig.suptitle("Bearing1_1 (cond.1: 1800rpm/4000N) - feature trends over life", fontsize=12)
fig.tight_layout()
png = os.path.join(OUT_DIR, "Bearing1_1_feature_trends.png")
fig.savefig(png, dpi=110)
print("saved plot ->", png)

# --- 关键统计: 前10%健康段 vs 末段, 看上升趋势 ---
h_end = int(0.10 * n)
print(f"\n=== n={n} snapshots; health window = first {h_end} ===")
print(f"{'feature':10s}{'health_mean':>14s}{'last10%_mean':>14s}{'ratio':>8s}")
for f in feats:
    for ch in ["h", "v"]:
        col = data[f + "_" + ch]
        hm = col[:h_end].mean()
        lm = col[-h_end:].mean()
        ratio = lm / (hm + 1e-12)
        print(f"{f+'_'+ch:10s}{hm:14.4f}{lm:14.4f}{ratio:8.2f}")

# Spearman(特征, 时间) 看单调性
from scipy.stats import spearmanr
print(f"\n{'feature':10s}{'Spearman(feat, time)':>22s}")
for f in feats:
    for ch in ["h", "v"]:
        rho, _ = spearmanr(data[f + "_" + ch], idx)
        print(f"{f+'_'+ch:10s}{rho:22.3f}")
