using System;
using System.Diagnostics;
using System.Threading;

namespace MachineCollector;

/// <summary>
/// 合成振动源：按配置的 rate / samplesPerChannel 产生批次，节奏贴近真实采集，
/// 用于无 NI 硬件时端到端验证落库/COPY/合并链路与吞吐。
/// 每通道 = 基频正弦 + 噪声；通道间相位错开。
/// </summary>
public sealed class SimulatedVibrationSource : IVibrationSource
{
    private readonly int _rate;
    private readonly int _samplesPerChannel;
    private readonly int _channels;
    private Thread? _thread;
    private volatile bool _running;
    private long _sampleIndex;
    private readonly Random _rng = new();

    public event Action<double[][]>? BatchReady;
    public event Action<string>? Faulted; // 模拟源不会故障，仅为满足接口

    public SimulatedVibrationSource(AcquisitionOptions opt)
    {
        _rate = opt.Rate;
        _samplesPerChannel = opt.SamplesPerChannel;
        _channels = Math.Max(1, opt.ChannelCount);
    }

    public void Start()
    {
        if (_running) return;
        _running = true;
        _thread = new Thread(Loop) { IsBackground = true, Name = "sim-acq" };
        _thread.Start();
    }

    private void Loop()
    {
        // 每批理论耗时（秒）：samplesPerChannel / rate
        double batchSeconds = (double)_samplesPerChannel / _rate;
        var sw = Stopwatch.StartNew();
        long nextBatchAt = 0; // 以微秒计的目标时刻
        long batchMicros = (long)(batchSeconds * 1_000_000);

        while (_running)
        {
            var batch = new double[_samplesPerChannel][];
            for (int i = 0; i < _samplesPerChannel; i++)
            {
                double t = (_sampleIndex + i) / (double)_rate;
                var row = new double[_channels];
                for (int ch = 0; ch < _channels; ch++)
                {
                    double phase = ch * Math.PI / 4;
                    row[ch] = 0.5 * Math.Sin(2 * Math.PI * 60 * t + phase)   // 60Hz 基频
                            + 0.1 * Math.Sin(2 * Math.PI * 180 * t)          // 谐波
                            + (_rng.NextDouble() - 0.5) * 0.05;              // 噪声
                }
                batch[i] = row;
            }
            _sampleIndex += _samplesPerChannel;

            BatchReady?.Invoke(batch);

            // 节流到接近真实节奏，避免 CPU 空转过快
            nextBatchAt += batchMicros;
            long now = sw.ElapsedTicks * 1_000_000 / Stopwatch.Frequency;
            long sleepMicros = nextBatchAt - now;
            if (sleepMicros > 1000) Thread.Sleep((int)(sleepMicros / 1000));
        }
    }

    public void Stop()
    {
        _running = false;
        _thread?.Join(1000);
        _thread = null;
    }

    public void Dispose() => Stop();
}
