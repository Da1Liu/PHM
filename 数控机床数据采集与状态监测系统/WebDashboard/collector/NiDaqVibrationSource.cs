#if NIDAQ
using System;
using NationalInstruments;
using NationalInstruments.DAQmx;

namespace MachineCollector;

/// <summary>
/// 真实 NI-DAQmx 采集源。移植自桌面端 Form2.start_sampling / OnDataReady，去掉 WinForms。
/// 仅在安装 NI-DAQmx (.NET) 且以 -p:DefineConstants=NIDAQ 编译时编入。
/// 用 NI MAX 创建模拟设备即可无真实硬件验证。
/// </summary>
public sealed class NiDaqVibrationSource : IVibrationSource
{
    private readonly AcquisitionOptions _opt;
    private Task? _task;
    private Task? _runningTask;
    private AnalogMultiChannelReader? _reader;
    private AsyncCallback? _callback;
    private AnalogWaveform<double>[]? _data;

    public event Action<double[][]>? BatchReady;
    public event Action<string>? Faulted;

    public NiDaqVibrationSource(AcquisitionOptions opt) => _opt = opt;

    public void Start()
    {
        _task = new Task();
        foreach (var ch in _opt.Channels)
        {
            var ai = _task.AIChannels.CreateAccelerometerChannel(
                ch.PhysicalChannel, "",
                AITerminalConfiguration.Pseudodifferential, -50, 50,
                (float)ch.SensitivityMvPerG, AIAccelerometerSensitivityUnits.MillivoltsPerG,
                AIExcitationSource.Internal, 0.002, AIAccelerationUnits.G);
            ai.Coupling = AICoupling.AC;
        }

        _task.Timing.ConfigureSampleClock("", _opt.Rate, SampleClockActiveEdge.Rising,
            SampleQuantityMode.ContinuousSamples, _opt.SamplesPerChannel);
        _task.Control(TaskAction.Verify);
        _task.Stream.Buffer.InputBufferSize = _opt.InputBufferSize;

        _runningTask = _task;
        _reader = new AnalogMultiChannelReader(_task.Stream) { SynchronizeCallbacks = false };
        _callback = OnDataReady;
        _reader.BeginReadWaveform(_opt.SamplesPerChannel, _callback, _task);
    }

    private void OnDataReady(IAsyncResult result)
    {
        if (_runningTask is null || result.AsyncState != _runningTask) return;
        try
        {
            _data = _reader!.EndReadWaveform(result);
            int samples = _data[0].SampleCount;
            int channels = _data.Length;
            var batch = new double[samples][];
            for (int i = 0; i < samples; i++)
            {
                var row = new double[channels];
                for (int ch = 0; ch < channels; ch++)
                    row[ch] = _data[ch].Samples[i].Value;
                batch[i] = row;
            }
            BatchReady?.Invoke(batch);
            _reader.BeginMemoryOptimizedReadWaveform(_opt.SamplesPerChannel, _callback!, _task!, _data);
        }
        catch (DaqException ex)
        {
            Console.Error.WriteLine($"[nidaq] 读取错误: {ex.Message}");
            _runningTask = null;
            Faulted?.Invoke(ex.Message); // 通知守护进程自停（不再僵尸）
        }
    }

    public void Stop()
    {
        _runningTask = null;
        try { _task?.Stop(); } catch { }
        _task?.Dispose();
        _task = null;
    }

    public void Dispose() => Stop();
}
#endif
