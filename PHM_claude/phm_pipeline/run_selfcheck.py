"""
端到端自检: 把 UCI 液压回放成"每天到货的数据流", 驱动整条生命周期 pipeline,
产出自检报告 + 曲线. 既是真机自检程序本体, 又第一次把冷启动->过渡->成熟跑通.

回放设计:
- 子集 cooler=100 & stable=0 (同 step7-9).
- 顺序: 健康 pump=0 全部先到 (累积基线), 然后 pump=1, 再 pump=2 (基线建成后注入退化).
- 合成"天": 每天 samples_per_day 条, 使跨日天数随样本累积, 触发成熟期门槛.

验收判据:
- 健康尾段 FAR < 5%.
- 阶段切换无可见跳变 (continuity.discontinuous = False).
- score/health 随 pump 等级单调.
- pump=2 样本贡献分解指向压力/流量/功率特征.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import spearmanr

from phm_pipeline.config import hydraulic_v1
from phm_pipeline.datasource import FileSource
from phm_pipeline.features import extract_vector
from phm_pipeline.alarm import AlarmState
from phm_pipeline.lifecycle import LifecycleManager
from phm_pipeline.model import BaselineModel
from phm_pipeline.score import explain
from phm_pipeline import selfcheck as sc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "uci_hydraulic")
OUT_DIR = os.path.join(ROOT, "outputs", "selfcheck")
os.makedirs(OUT_DIR, exist_ok=True)

SAMPLES_PER_DAY = 3   # 每天 ~3 次交班 (落地文档假设)


def build_stream():
    """提取特征, 排成 健康->pump1->pump2 的回放流, 附合成天号."""
    cfg = hydraulic_v1()
    channels = ["PS1", "PS2", "PS3", "FS1", "FS2", "EPS1", "VS1", "SE", "TS1", "TS2"]
    src = FileSource(DATA_DIR, channels=channels, temps=[],
                     row_filter=lambda r: r["cooler"] == 100 and r["stable"] == 0)
    recs = list(src.records())
    feats, pumps, names = [], [], None
    for rec in recs:
        vec, names = extract_vector(rec, cfg.feature_specs, cfg.derived)
        feats.append(vec)
        pumps.append(rec.meta["pump"])
    feats = np.array(feats)
    pumps = np.array(pumps)
    # 回放顺序: 健康->pump1->pump2. 每个等级内部打乱, 消除 UCI 数据集
    # 按 valve/accumulator 工况扫描的排序假象 (真实标准采集程序固定工况,
    # 同一健康样本跨日可交换). 否则训练/打分落在不同工况上, FAR 虚高.
    rng = np.random.default_rng(20260615)
    order = []
    for p in [0, 1, 2]:
        idx = np.where(pumps == p)[0]
        rng.shuffle(idx)
        order.append(idx)
    order = np.concatenate(order)
    feats, pumps, recs = feats[order], pumps[order], [recs[i] for i in order]
    days = np.arange(len(order)) // SAMPLES_PER_DAY
    return cfg, names, feats, pumps, recs, days


def run():
    cfg, names, X, pump, recs, days = build_stream()
    print(f"stream: n={len(X)}, features={len(names)}, "
          f"pump0={np.sum(pump==0)} pump1={np.sum(pump==1)} pump2={np.sum(pump==2)}")

    mgr = LifecycleManager(cfg=cfg, refit_every=10)
    rows = []
    for i in range(len(X)):
        res = mgr.observe(X[i], int(days[i]))
        rows.append({
            "i": i, "pump": int(pump[i]), "day": int(days[i]),
            "n": res.n, "n_days": res.n_days, "stage": res.stage,
            "score": res.score, "health": res.health, "blended": int(res.blended),
        })

    health = np.array([r["health"] for r in rows])
    stage = np.array([r["stage"] for r in rows])
    score = np.array([r["score"] for r in rows])
    is_healthy = pump == 0

    # --- 诊断 1: FAR (成熟期健康样本) ---
    # 1a 原始单点超限率 (≈UCL分位数+小样本噪声); 1b 部署告警率 (EWMA+K连续去抖).
    mature_healthy = is_healthy & (stage == 3)
    far_raw = sc.far(score[mature_healthy], ucl=1.0)

    alarm = AlarmState(ucl_score=1.0, lam=cfg.ewma_lambda, k_consecutive=cfg.k_consecutive)
    debounced_alarms = 0
    n_mature_healthy = 0
    for i in range(len(X)):
        if stage[i] != 3:
            continue
        res_alarm = alarm.update(score[i])
        if is_healthy[i]:
            n_mature_healthy += 1
            debounced_alarms += int(res_alarm["l2_alarm"])
    far_debounced = 100.0 * debounced_alarms / max(n_mature_healthy, 1)
    far_mature = far_debounced  # 部署判据以去抖告警率为准

    # --- 诊断 2: 基线稳定性 (健康样本, 冻结前60条 vs 全量) ---
    Xh = X[is_healthy]
    stab = sc.baseline_stability(Xh, freeze_n=60, feature_names=names, keep=cfg.pca_keep)

    # --- 诊断 3: 阶段切换连续性 (原始 + EWMA 平滑趋势) ---
    from phm_pipeline.alarm import ewma as ewma_fn
    health_ewma = ewma_fn(health, lam=cfg.ewma_lambda)
    cont = sc.continuity(health, stage)
    cont_ewma = sc.continuity(health_ewma, stage)

    # --- 诊断 4: 单调性 (成熟期, 用最终全量模型给所有样本统一打分) ---
    final_model = BaselineModel(feature_names=names, keep=cfg.pca_keep).fit(Xh)
    score_all = final_model.score(X)
    health_by_pump = sc.monotonicity_by_level(health, pump)
    score_by_pump = sc.monotonicity_by_level(score_all, pump)
    rho, _ = spearmanr(score_all, pump)

    # --- 诊断 5: 贡献分解 (一条 pump=2 样本) ---
    p2_idx = np.where(pump == 2)[0]
    expl = explain(final_model, X[p2_idx[len(p2_idx) // 2]], top=3)

    # --- 诊断 6: 数据质检 (UCI 无 shift_hours, 应被标记 missing) ---
    qc = [sc.check_record(r, expected_program="uci_standard_cycle") for r in recs[:5]]
    qc_missing = sum("shift_hours_missing" in q["issues"] for q in qc)

    # ---- 写报告 ----
    report_path = os.path.join(OUT_DIR, "selfcheck_report.csv")
    with open(report_path, "w", encoding="utf-8", newline="") as f:
        f.write("metric,value,pass\n")
        f.write(f"far_debounced_alarm_pct,{far_debounced:.3f},{far_debounced < 5.0}\n")
        f.write(f"far_raw_exceedance_pct,{far_raw:.3f},\n")
        f.write(f"baseline_far_frozen60_pct,{stab['far_frozen']:.3f},\n")
        f.write(f"baseline_far_full_pct,{stab['far_full']:.3f},\n")
        f.write(f"continuity_boundary_jump,{cont['boundary_max_jump']:.4f},{not cont['discontinuous']}\n")
        f.write(f"continuity_step_p95,{cont['step_p95']:.4f},\n")
        f.write(f"spearman_score_pump,{rho:.3f},{rho > 0.5}\n")
        mono = (score_by_pump[0] < score_by_pump[1] < score_by_pump[2])
        f.write(f"score_pump0,{score_by_pump[0]:.4f},{mono}\n")
        f.write(f"score_pump1,{score_by_pump[1]:.4f},\n")
        f.write(f"score_pump2,{score_by_pump[2]:.4f},\n")
        f.write(f"health_pump0,{health_by_pump.get(0, float('nan')):.4f},\n")
        f.write(f"health_pump2,{health_by_pump.get(2, float('nan')):.4f},\n")

    scores_path = os.path.join(OUT_DIR, "selfcheck_stream.csv")
    with open(scores_path, "w", encoding="utf-8", newline="") as f:
        f.write("i,pump,day,n,n_days,stage,score,health,blended\n")
        for r in rows:
            f.write(f"{r['i']},{r['pump']},{r['day']},{r['n']},{r['n_days']},"
                    f"{r['stage']},{r['score']:.5f},{r['health']:.5f},{r['blended']}\n")

    plot_path = save_plot(rows, health, health_ewma, stage, score_all, pump)

    # ---- 控制台总结 ----
    print("\n=== 自检结果 ===")
    print(f"[FAR]   去抖告警 FAR = {far_debounced:.2f}%  "
          f"({'PASS' if far_debounced < 5 else 'FAIL'}, 判据<5%); "
          f"原始单点超限率 = {far_raw:.2f}% (成熟期健康样本 n={n_mature_healthy})")
    print(f"[稳定性] 冻结60条基线 FAR={stab['far_frozen']:.2f}% vs 全量 FAR={stab['far_full']:.2f}% "
          f"(尾段 n={stab['tail_n']})")
    print(f"[连续性] 原始: 边界跳变={cont['boundary_max_jump']:.3f}/波动p95={cont['step_p95']:.3f}; "
          f"EWMA趋势: 边界跳变={cont_ewma['boundary_max_jump']:.3f}/波动p95={cont_ewma['step_p95']:.3f}  "
          f"({'PASS' if not cont['discontinuous'] else 'FAIL'}, 判据=原始连续性无可见跳变; EWMA 仅参考)")
    print(f"[单调性] score pump0/1/2 = {score_by_pump[0]:.3f}/{score_by_pump[1]:.3f}/{score_by_pump[2]:.3f}, "
          f"Spearman={rho:.3f}  ({'PASS' if mono and rho > 0.5 else 'FAIL'})")
    print(f"        health pump0/2 = {health_by_pump.get(0):.3f}/{health_by_pump.get(2):.3f}")
    print(f"[贡献]  pump=2 样本: 主导空间={expl['dominant_space']}, "
          f"top_T2={[(n, round(v,2)) for n,v in expl['top_t2']]}")
    print(f"[质检]  前5条记录 shift_hours_missing 标记数={qc_missing}/5 (UCI 无班次, 预期=5)")
    print(f"\nsaved -> {report_path}")
    print(f"saved -> {scores_path}")
    print(f"saved -> {plot_path}")


def save_plot(rows, health, health_ewma, stage, score_all, pump):
    n = len(rows)
    x = np.arange(n)
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)

    ax = axes[0]
    for s, c in [(1, "#fde0dd"), (2, "#fff2cc"), (3, "#e2f0d9")]:
        ax.fill_between(x, 0, 1, where=(stage == s), color=c, alpha=0.6,
                        label=f"stage{s}", step="mid")
    ax.plot(x, health, lw=0.7, color="tab:blue", alpha=0.45, label="health (raw)")
    ax.plot(x, health_ewma, lw=1.6, color="tab:blue", label="health (EWMA trend)")
    ax.set_ylabel("health")
    ax.set_ylim(0, 1.05)
    ax.set_title("Lifecycle health (replay: healthy -> pump1 -> pump2)")
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1]
    ax.plot(x, score_all, lw=1.0, color="tab:red")
    ax.axhline(1.0, color="k", ls="--", lw=0.8, label="UCL(score=1)")
    ax.set_ylabel("score = max(T2/UCL, SPE/UCL)")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[2]
    ax.plot(x, pump, lw=1.0, color="tab:green", drawstyle="steps-mid")
    ax.set_ylabel("pump leak level")
    ax.set_xlabel("sample index (replay order)")
    ax.set_yticks([0, 1, 2])
    ax.grid(alpha=0.25)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "selfcheck_curves.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


if __name__ == "__main__":
    run()
