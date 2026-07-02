"""
PRONOSTIA 健康曲线验证 - Step 1: 特征提取
对应 pronostia_health_curve_plan.md 的停下点 1。

只做特征提取与自检画图，不做评分/告警。
每个 acc 快照文件 -> 一组振动时域特征。
"""
import os
import glob
import numpy as np

# --- 路径 ---
BASE = os.path.join(
    os.path.dirname(__file__),
    "data", "femto_tmp",
    "ieee-phm-2012-data-challenge-dataset-master",
    "Learning_set",
)
BEARING = "Bearing1_1"
OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "step1_features")
os.makedirs(OUT_DIR, exist_ok=True)

# acc 文件列: [时, 分, 秒, 微秒, 水平加速度, 垂直加速度]
COL_H = 4  # horizontal
COL_V = 5  # vertical


def extract_features(signal):
    """单通道信号 -> 4 个时域特征 (RMS, 峭度, 峰值因子, 峰峰值)"""
    x = signal.astype(np.float64)
    rms = np.sqrt(np.mean(x**2))
    peak = np.max(np.abs(x))
    mean = np.mean(x)
    std = np.std(x)
    # 峭度 (Fisher, 正态=0; 这里用普通定义 normal=3 更直观对照冲击)
    kurt = np.mean(((x - mean) / (std + 1e-12)) ** 4)
    crest = peak / (rms + 1e-12)
    p2p = np.max(x) - np.min(x)
    return rms, kurt, crest, p2p


def load_snapshot(path):
    """读单个 acc 快照, 返回 (horiz, vert)"""
    d = np.genfromtxt(path, delimiter=",")
    return d[:, COL_H], d[:, COL_V]


def main():
    files = sorted(glob.glob(os.path.join(BASE, BEARING, "acc_*.csv")))
    print(f"{BEARING}: {len(files)} snapshots")

    rows = []
    for i, f in enumerate(files):
        h, v = load_snapshot(f)
        fh = extract_features(h)
        fv = extract_features(v)
        rows.append((i, *fh, *fv))
        if (i + 1) % 500 == 0:
            print(f"  processed {i+1}/{len(files)}")

    cols = [
        "idx",
        "rms_h", "kurt_h", "crest_h", "p2p_h",
        "rms_v", "kurt_v", "crest_v", "p2p_v",
    ]
    data = np.array(rows)
    # 存 csv
    csv_path = os.path.join(OUT_DIR, f"{BEARING}_features.csv")
    np.savetxt(csv_path, data, delimiter=",", header=",".join(cols), comments="")
    print(f"saved features -> {csv_path}")
    return data, cols


if __name__ == "__main__":
    main()
