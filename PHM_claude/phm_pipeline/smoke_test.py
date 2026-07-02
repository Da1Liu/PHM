"""
冒烟测试: 用 MockSource 单条/多条合成记录跑通每一层, 验证模块可组合.
运行: python -m phm_pipeline.smoke_test
"""
import numpy as np

from phm_pipeline.alarm import AlarmState
from phm_pipeline.covariate import TempResidualizer
from phm_pipeline.datasource import MockSource
from phm_pipeline.features import FeatureSpec, extract_vector, extract_temps
from phm_pipeline.lifecycle import LifecycleManager
from phm_pipeline.model import BaselineModel
from phm_pipeline.score import explain, health_from_score
from phm_pipeline.config import SystemConfig


def main():
    specs = [
        FeatureSpec("CH0", "ch0_mean", "mean"),
        FeatureSpec("CH0", "ch0_std", "std"),
        FeatureSpec("CH1", "ch1_rms", "rms"),
        FeatureSpec("CH2", "ch2_mean", "mean"),
    ]

    # 1. 单条记录 -> 特征向量 + 温度协变量
    rec = MockSource.synth(n_channels=3, length=600, seed=1)
    vec, names = extract_vector(rec, specs)
    tvec, tnames = extract_temps(rec)
    assert vec.shape == (4,) and len(names) == 4
    assert tvec.shape[0] == 1, tnames
    print(f"[features] names={names}, vec={np.round(vec,3)}")

    # 2. 温度残差化 (混淆温度回归剔除)
    X = np.array([extract_vector(MockSource.synth(3, 600, s), specs)[0] for s in range(80)])
    T = np.array([extract_temps(MockSource.synth(3, 600, s))[0] for s in range(80)])
    resid = TempResidualizer().fit(X, T).transform(X, T)
    assert resid.shape == X.shape
    print(f"[covariate] residual shape={resid.shape}")

    # 3. BaselineModel fit/score (样本外 UCL) + 贡献分解
    model = BaselineModel(feature_names=names, keep=0.95).fit(X[:60], X[60:])
    s = model.score(X)
    assert s.shape == (80,)
    expl = explain(model, X[0])
    assert "top_t2" in expl and 0 <= expl["health"] <= 1
    print(f"[model] k={model.W.shape[1]}, score[0]={s[0]:.3f}, health={expl['health']:.3f}")

    # 4. 告警状态机
    alarm = AlarmState(ucl_score=1.0, lam=0.15, k_consecutive=5)
    out = [alarm.update(float(sc)) for sc in s]
    print(f"[alarm] last={out[-1]['source'] or 'none'}, ewma={out[-1]['ewma']:.3f}")

    # 5. LifecycleManager 在线喂入 (跨阶段)
    cfg = SystemConfig(name="mock", feature_specs=specs,
                       stage1_max_n=10, stage2_max_n=30, stage3_min_days=3,
                       stage3_min_ratio=8, blend_lo=20, blend_hi=60)
    mgr = LifecycleManager(cfg=cfg, refit_every=10)
    stages = set()
    for i in range(80):
        x = extract_vector(MockSource.synth(3, 600, 1000 + i), specs)[0]
        r = mgr.observe(x, day=i // 3)
        stages.add(r.stage)
        assert 0 <= r.health <= 1
    print(f"[lifecycle] stages seen={sorted(stages)}, final n={mgr.n}, days={mgr.n_days}")

    assert health_from_score(0.0) == 1.0
    print("\nSMOKE TEST OK")


if __name__ == "__main__":
    main()
