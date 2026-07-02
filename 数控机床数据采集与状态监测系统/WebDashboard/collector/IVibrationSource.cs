using System;

namespace MachineCollector;

/// <summary>
/// 振动采集源抽象。一批数据 = double[sampleCount][channelCount]。
/// 真实实现 = NI-DAQmx（BeginReadWaveform 回调）；模拟实现 = 合成波形。
/// 解耦后采集回路（NI）是唯一 native 部分；落库/合并等都在外层与源无关。
/// </summary>
public interface IVibrationSource : IDisposable
{
    /// <summary>每批可用数据回调：batch[i] 为第 i 个采样点的各通道值。</summary>
    event Action<double[][]>? BatchReady;

    /// <summary>采集致命错误（如 NI 设备被移除）。守护进程据此自停并清标志，避免僵尸。</summary>
    event Action<string>? Faulted;

    void Start();
    void Stop();
}
