"""
PRONOSTIA 健康曲线验证 - Step 2: 评分与告警
对应 pronostia_health_curve_plan.md 的停下点 2。

链路: 前10%健康基线 -> Hotelling T2 (单一指标) -> 健康度映射 -> EWMA 告警
主用水平通道 (Step1 自检确认水平方向退化敏感性远强于垂直)。
特征选择/PCA 留待后续验证, 本步用固定 4 特征。
"""
import os
import numpy as np
from scipy.stats import spearmanr, f as f_dist

OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "step2_scoring")
os.makedirs(OUT_DIR, exist_ok=True)
FEAT_CSV = os.path.join(os.path.dirname(__file__), "outputs", "step1_features",
                        "Bearing1_1_features.csv")

# 主用水平通道 4 特征
FEATURES = ["rms_h", "kurt_h", "crest_h", "p2p_h"]
HEALTH_FRAC = 0.10   # 健康基线窗口比例 (敏感性检查另跑)
ALPHA = 1.0          # 健康度映射系数 (做几组对比)


def hotelling_t2(X, mu, cov_inv):
    """逐行 T2 = (x-mu) Σ^-1 (x-mu)^T"""
    d = X - mu
    return np.einsum("ij,jk,ik->i", d, cov_inv, d)


def run(health_frac=HEALTH_FRAC, alpha=ALPHA, verbose=True):
    data = np.genfromtxt(FEAT_CSV, delimiter=",", names=True)
    idx = data["idx"].astype(int)
    n = len(idx)
    X = np.column_stack([data[f] for f in FEATURES])

    # 标准化用健康段统计
    h_end = int(health_frac * n)
    Xh = X[:h_end]
    mu_std = Xh.mean(axis=0)
    sd_std = Xh.std(axis=0) + 1e-12
    Xz = (X - mu_std) / sd_std
    Xhz = Xz[:h_end]

    # 健康基线均值/协方差 (标准化空间)
    mu = Xhz.mean(axis=0)
    cov = np.cov(Xhz, rowvar=False)
    cov_inv = np.linalg.pinv(cov)

    t2 = hotelling_t2(Xz, mu, cov_inv)

    # --- 控制限 UCL ---
    # 经验分位数 (健康段 99%)
    ucl_emp = np.quantile(t2[:h_end], 0.99)
    # F 分布理论 UCL (p 维, m 健康样本)
    p = len(FEATURES)
    m = h_end
    fcrit = f_dist.ppf(0.99, p, m - p)
    ucl_f = p * (m - 1) * (m + 1) / (m * (m - p)) * fcrit

    # 健康度映射: 用健康段 T2 中位数做参考尺度
    t2_ref = np.median(t2[:h_end]) + 1e-12
    health = np.exp(-alpha * t2 / (t2_ref * 10))  # /10 让健康段 health~1

    # --- 告警: 连续 K 点超 UCL 才告警 (去抖, 滤掉孤立尖峰) ---
    # 两种 UCL 并列对比
    K = 5  # 连续超阈点数
    def first_consecutive_alarm(t2arr, ucl, k):
        above = t2arr > ucl
        run = 0
        for t in range(len(above)):
            run = run + 1 if above[t] else 0
            if run >= k:
                return t - k + 1  # 连续段的起点
        return -1
    alarms_dbnc = {
        "empirical": first_consecutive_alarm(t2, ucl_emp, K),
        "f_theory": first_consecutive_alarm(t2, ucl_f, K),
    }

    # EWMA 仍保留作趋势可视化 (不再单独用于触发)
    score = t2 / ucl_emp
    results = {}
    for lam in [0.10, 0.15, 0.20]:
        ewma = np.zeros(n)
        ewma[0] = score[0]
        for t in range(1, n):
            ewma[t] = lam * score[t] + (1 - lam) * ewma[t - 1]
        results[lam] = (ewma, -1)

    # --- 指标 ---
    # 健康段误报率: 健康段中 t2 > ucl_emp 的比例
    far = np.mean(t2[:h_end] > ucl_emp)
    # 退化段单调性: 用后 (1-health_frac) 段, health vs 距失效时间
    deg_slice = slice(h_end, n)
    time_to_fail = (n - 1) - idx[deg_slice]  # 越接近失效越小
    rho_health, _ = spearmanr(health[deg_slice], time_to_fail)  # 期望正: 距失效大=health高

    if verbose:
        print(f"=== Bearing1_1 | health_frac={health_frac} alpha={alpha} ===")
        print(f"n={n}, health window={h_end}")
        print(f"UCL empirical(99%)={ucl_emp:.2f}  UCL F-theory={ucl_f:.2f}")
        print(f"health-segment false alarm rate = {far*100:.2f}%")
        print(f"Spearman(health, time-to-failure) on degradation = {rho_health:.3f}")
        print(f"  (正值=越接近失效 health 越低, 符合预期)")
        print()
        print(f"--- consecutive-K alarm (K={K}) ---")
        for name, ai in alarms_dbnc.items():
            if ai > 0:
                pct = 100 * ai / n
                lead = n - ai
                print(f"  UCL[{name}]: first alarm @ {ai} ({pct:.1f}% life), "
                      f"lead={lead} snaps (~{lead*10/60:.0f} min)")
            else:
                print(f"  UCL[{name}]: NO alarm")

    return dict(idx=idx, n=n, t2=t2, health=health, score=score,
                ucl_emp=ucl_emp, ucl_f=ucl_f, h_end=h_end, K=K,
                far=far, rho_health=rho_health, results=results,
                alarms_dbnc=alarms_dbnc)


if __name__ == "__main__":
    out = run()
    np.savez(os.path.join(OUT_DIR, "Bearing1_1_scores.npz"),
             idx=out["idx"], t2=out["t2"], health=out["health"],
             score=out["score"])
    print("\nsaved scores -> outputs/step2_scoring/Bearing1_1_scores.npz")

    # 敏感性检查: 健康窗口 5/10/20%
    print("\n=== sensitivity: health window fraction (alarm = consecutive-K, UCL empirical) ===")
    for hf in [0.05, 0.10, 0.20]:
        o = run(health_frac=hf, verbose=False)
        ai = o["alarms_dbnc"]["empirical"]
        pct = 100 * ai / o["n"] if ai > 0 else -1
        tag = f"alarm@{ai}({pct:.1f}%)" if ai > 0 else "NO alarm"
        print(f"  frac={hf}: FAR={o['far']*100:.2f}%  "
              f"Spearman={o['rho_health']:.3f}  {tag}")
