"""Step 2 画图 + 告警点核实"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "step2_scoring")
d = np.load(os.path.join(OUT_DIR, "Bearing1_1_scores.npz"))
idx, t2, health, score = d["idx"], d["t2"], d["health"], d["score"]
n = len(idx)
h_end = int(0.10 * n)
ucl_emp = 32.27

# 重算 EWMA lambda=0.15 (趋势可视化)
lam = 0.15
ewma = np.zeros(n); ewma[0] = score[0]
for t in range(1, n):
    ewma[t] = lam * score[t] + (1 - lam) * ewma[t-1]

# 去抖告警: 连续 K 点超 UCL
K = 5
ucl_f = 13.75
def first_consec(arr, ucl, k):
    above = arr > ucl; run = 0
    for t in range(len(above)):
        run = run+1 if above[t] else 0
        if run >= k: return t-k+1
    return -1
alarm_emp = first_consec(t2, ucl_emp, K)
alarm_f = first_consec(t2, ucl_f, K)

fig, axes = plt.subplots(3, 1, figsize=(12, 11), sharex=True)

# T2 + 两种 UCL + 两个告警点
axes[0].plot(idx, t2, lw=0.6, color="C3")
axes[0].axhline(ucl_emp, color="k", ls="--", lw=1, label=f"UCL emp(99%)={ucl_emp:.0f}")
axes[0].axhline(ucl_f, color="purple", ls=":", lw=1, label=f"UCL F-theory={ucl_f:.0f}")
axes[0].axvspan(0, h_end, alpha=0.12, color="green", label="health baseline window")
axes[0].axvline(alarm_emp, color="red", lw=1, alpha=0.7)
axes[0].axvline(alarm_f, color="orange", lw=1, alpha=0.7)
axes[0].set_ylabel("Hotelling T2"); axes[0].set_yscale("log")
axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)

# health
axes[1].plot(idx, health, lw=0.7, color="C0")
axes[1].axvspan(0, h_end, alpha=0.12, color="green")
axes[1].axvline(alarm_emp, color="red", lw=1, alpha=0.7)
axes[1].set_ylabel("health score"); axes[1].grid(alpha=0.3)

# EWMA (趋势) + 告警点
axes[2].plot(idx, ewma, lw=0.8, color="C2", label=f"EWMA(score), lam={lam}")
axes[2].axhline(1.0, color="k", ls="--", lw=1, label="T2=UCL_emp level")
axes[2].axvline(alarm_emp, color="red", lw=1.2, label=f"alarm(emp) @ {alarm_emp} ({100*alarm_emp/n:.0f}%)")
axes[2].axvline(alarm_f, color="orange", lw=1.2, label=f"alarm(F) @ {alarm_f} ({100*alarm_f/n:.0f}%)")
axes[2].set_ylabel("EWMA score"); axes[2].set_xlabel("snapshot index")
axes[2].set_yscale("log"); axes[2].legend(fontsize=8); axes[2].grid(alpha=0.3)

fig.suptitle("Bearing1_1 health curve / T2 / EWMA alarm", fontsize=12)
fig.tight_layout()
png = os.path.join(OUT_DIR, "Bearing1_1_health_curve.png")
fig.savefig(png, dpi=110); print("saved ->", png)

# --- 核实去抖后告警点: 看告警起点后 T2 是否持续高于 UCL (真退化) ---
print(f"\n=== debounced alarm (K={K}) ===")
print(f"  UCL empirical: alarm @ {alarm_emp} ({100*alarm_emp/n:.1f}% life)")
print(f"  UCL F-theory:  alarm @ {alarm_f} ({100*alarm_f/n:.1f}% life)")

for name, a in [("empirical", alarm_emp), ("f_theory", alarm_f)]:
    post = t2[a:a+200]
    frac_above = np.mean(post > (ucl_emp if name=="empirical" else ucl_f))
    print(f"  [{name}] after alarm next 200 snaps: {frac_above*100:.0f}% stay above UCL "
          f"(高=真退化持续)")

# 看整条命中率分布: T2 超 UCL 的点都在哪
above = idx[t2 > ucl_emp]
print(f"\ntotal snapshots T2>UCL: {len(above)} / {n}")
print(f"  first 10%: {np.sum(above < h_end)}")
print(f"  10-50%: {np.sum((above>=h_end)&(above<0.5*n))}")
print(f"  50-100%: {np.sum(above>=0.5*n)}")
