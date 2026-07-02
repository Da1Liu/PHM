"""
phm_pipeline: 机床健康基线共享核 + 生命周期 + 真机自检 (v1).

设计原则:
- 采集通道解耦: 所有逻辑藏在 DataSource 接口后, 现在对回放数据开发,
  真实采集接入后只换最底层 DataSource, 上层不动.
- 算法块来自已验证脚本 step1-9, 纯 numpy, SVD, pinv.
- 成熟期算法: PCA + Hotelling T2 + SPE (step7-9 证明).

参见 cnc_multisensor_health_baseline_implementation_plan.md 与
multisensor_covariance_baseline_validation_plan.md.
"""

__version__ = "0.1.0"
