"""
系统配置: 把"特征集 / 温度角色 / 物理限 / 算法超参 / 分层键 / 阶段阈值"
集中到每个系统的 SystemConfig.

v1 只实现液压 (系统效率退化, 单基线). 进给/主轴预留占位, 不在 v1 启用.

液压特征集刻意与 step7 一致, 使共享核能在静态切分模式下复现 step7-9 数值
(回归锚点). UCI 的 TS1/TS2 是油/冷却温度, 属"耦合温度", 保留进向量,
故液压 v1 不做混淆温度回归剔除 (confounder_temps 为空).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from .features import FeatureSpec, q_over_p, DerivedFn


@dataclass
class SystemConfig:
    name: str
    feature_specs: List[FeatureSpec]
    derived: Dict[str, DerivedFn] = field(default_factory=dict)
    # 混淆温度: 回归剔除 (角色=confounder). 耦合温度直接在 feature_specs 里, 不列此处.
    confounder_temps: List[str] = field(default_factory=list)
    # L1 物理限: 特征名 -> (下界, 上界)
    physical_limits: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    # 基线分层键 (空=全样本单基线)
    baseline_by: Tuple[str, ...] = ()
    # 算法超参
    pca_keep: float = 0.95
    ucl_quantile: float = 0.99
    # 成熟期 UCL 标定法: "empirical"=样本外经验分位(默认, 与锚点一致);
    # "parametric"=T2~F + SPE~Jackson-Mudholkar 解析限(小样本稳, 可降门槛);
    # "auto"=n<empirical_min_n 用 parametric, 否则 empirical.
    ucl_method: str = "empirical"
    empirical_min_n: int = 150
    health_alpha: float = 3.0
    ewma_lambda: float = 0.15
    k_consecutive: int = 5
    # 生命周期阶段阈值
    stage1_max_n: int = 30       # n<30 工程先验期
    stage1_warmup: int = 5       # <warmup 条: 池子太小 std≈0 估不出基线散布, 健康度给中性 1.0
    stage2_max_n: int = 100      # 30<=n<100 分位评分期
    blend_lo: int = 50           # 混合过渡起点地板 (实际起点 = max(blend_lo, mature_min_n))
    blend_hi: int = 200          # 混合过渡终点
    stage3_min_days: int = 14    # 成熟期最少跨日
    stage3_min_ratio: int = 10   # 成熟期最少样本 = ratio*特征数 (n>=10p 经验规则)
    # C2 工况层 (缺省即不门控/不分箱, 向后兼容; 详见 regime.py/engine.py)
    regime_bins: Dict[str, Tuple[float, ...]] = field(default_factory=dict)  # 源标量键->升序档边界, 产出 {键}_bin
    confounder_fit_n: int = 30   # 混淆温残差化: 攒够此数后用前 fit_n 条拟合并冻结
    steady_channels: Tuple[str, ...] = ()    # 稳态门控依据通道 (空=不门控)
    steady_max_cv: float = 0.05              # 稳态窗内变异系数上限
    steady_max_slope_frac: float = 0.10      # 稳态窗内归一化漂移上限

    @property
    def feature_names(self) -> List[str]:
        return [s.name for s in self.feature_specs] + list(self.derived.keys())

    def mature_min_n(self) -> int:
        """进入成熟期(阶段三)的最少样本数: max(stage2_max_n, ratio*p)."""
        p = len(self.feature_names)
        return max(self.stage2_max_n, self.stage3_min_ratio * p)


def hydraulic_v1() -> SystemConfig:
    """液压系统 v1: 系统效率退化, 单基线. 特征集对齐 step7."""
    specs = [
        FeatureSpec("PS1", "ps1_mean", "mean"),
        FeatureSpec("PS1", "ps1_std", "std"),
        FeatureSpec("PS2", "ps2_mean", "mean"),
        FeatureSpec("PS3", "ps3_mean", "mean"),
        FeatureSpec("FS1", "fs1_mean", "mean"),
        FeatureSpec("FS2", "fs2_mean", "mean"),
        FeatureSpec("EPS1", "eps1_mean", "mean"),
        FeatureSpec("EPS1", "eps1_std", "std"),
        FeatureSpec("VS1", "vs1_mean", "mean"),
        FeatureSpec("VS1", "vs1_std", "std"),
        FeatureSpec("TS1", "ts1_mean", "mean"),  # 油温, 耦合温度, 进向量
        FeatureSpec("TS2", "ts2_mean", "mean"),
        FeatureSpec("SE", "se_mean", "mean"),
    ]
    derived = {"q_over_p": q_over_p("fs1_mean", "ps1_mean")}
    return SystemConfig(
        name="hydraulic",
        feature_specs=specs,
        derived=derived,
        confounder_temps=[],          # 液压油温属耦合, 不回归剔除
        physical_limits={},           # 现场标定后填入 (电机/泵规格书)
        baseline_by=(),               # 系统效率退化 -> 单基线
    )


# 进给/主轴 v1 占位 (不启用, 仅记录设计意图, 待后续实现).
FEED_PLACEHOLDER_NOTE = (
    "进给: 按 轴×方向×速度档 分层 (baseline_by=('axis','direction','feed_bin')); "
    "导轨磨损可由稳态电流RMS/std+正反向不对称检测; 反向间隙需换向段+跟随误差, "
    "第一版无数控权限不接入."
)
SPINDLE_PLACEHOLDER_NOTE = (
    "主轴: 按 rpm档 分层 (热态=协变量, 不分层: 效应平滑可残差化 + 热机后采协议标准化); "
    "前后轴承振动一起进同一条向量, 靠贡献分解归因到轴承; 不拆成独立基线 (保留跨轴承耦合关系)."
)


def spindle_field_v1() -> SystemConfig:
    """主轴系统振动基线 (整合现场 4 测点: 3 箱体 + 1 前轴承套).

    高频振动特征由采集端就地算好 (is_high_freq), 经 telemetry 进 rec.precomputed;
    特征名 = "{signal.code}_{reducer}", 与 PostgresSource 产出对齐.

    特征裁剪 (2026-06-23): 4 测点 RMS 相关 0.98-1.00, std/p2p 在共线测点间高度重复,
    每测点只留 rms(总能量) + kurtosis/crest(冲击性, 轴承点蚀/剥落敏感) -> p=12 (原 20).
    降名义维度即降成熟期门槛(ratio*p)并改善 n>p 条件数 (采集端仍可写全量, config 选子集).

    压缩档默认 (待真实主轴数据复标): ucl_method="auto"(小样本走参数化限) + 门槛 ~5p=60
    (stage2_max_n=60 + ratio=5, 而非 10p=120); 配合 NC 程序扫 rpm 并行填充各箱,
    早期成熟期约 2.5-5 周可达. 分层只按 rpm 档, 热态作协变量(不分层).
    """
    codes = ["vib_gearbox_1", "vib_gearbox_2", "vib_gearbox_3", "vib_spindle_front_bearing"]
    reducers = ["rms", "kurtosis", "crest"]   # 砍 std/p2p (共线冗余); 留总能量 + 冲击性
    specs = [FeatureSpec(c, f"{c}_{r}", r) for c in codes for r in reducers]
    return SystemConfig(
        name="spindle",
        feature_specs=specs,
        confounder_temps=[],          # 主轴混淆温度(电机)回归剔除待接 OPC UA 温度后启用
        physical_limits={},           # 现场标定
        baseline_by=("rpm_bin",),     # 按 rpm 档分层; 热态=协变量不分层 (热机后采 + 温度残差化)
        ucl_method="auto",            # 小样本参数化限, n>=empirical_min_n(150) 切经验分位
        stage2_max_n=60,              # 压低成熟期下限地板, 使 5p 门槛生效
        stage3_min_ratio=5,           # 成熟期门槛 = max(60, 5p=60) = 60 (原 10p=120)
        blend_hi=120,                 # 成熟期权重 50->120 升满 (默认 200 太慢, 配合早成熟)
    )


CONFIGS: Dict[str, Callable[[], SystemConfig]] = {
    "hydraulic": hydraulic_v1,
    "spindle": spindle_field_v1,
}
