using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;

namespace MachineCollector;

/// <summary>
/// 一次采集会话：振动源 → 队列 → 处理线程（按窗算特征落 vib_features；
/// 事件触发或手动抓取时把原始波形块落 vib_raw_blocks/vib_events）。
/// 采集与落库解耦（生产者/消费者），DB 延迟不阻塞采集回调。
/// </summary>
public sealed class Acquisition
{
    private readonly AcquisitionOptions _opt;
    private readonly VibStore _store;
    private readonly IVibrationSource _source;
    private readonly WindowAggregator _agg;
    private readonly BlockingCollection<double[][]> _queue = new(boundedCapacity: 512);
    private Task? _worker;

    private long _samples;          // 已处理样本数（每通道）
    private volatile string? _fault;
    private int _pendingCaptureSeq;
    private int _captureDone;

    public string Session { get; }
    public string Description => $"source={_opt.Source}, rate={_opt.Rate}Hz, ch={_opt.ChannelCount}, 窗={_opt.WindowSamples}样本, 事件={(_opt.EventEnabled ? $"RMS>{_opt.EventRmsThresholdG}g" : "关")}";
    public long SamplesProcessed => Interlocked.Read(ref _samples);
    public string? Fault => _fault;
    public int CaptureDone => _captureDone;

    public Acquisition(AcquisitionOptions opt, VibStore store, string session)
    {
        _opt = opt;
        _store = store;
        Session = session;
        _agg = new WindowAggregator(opt.ChannelCount, opt.WindowSamples);
        _source = CreateSource(opt);
    }

    public void RequestCapture(int seq) => _pendingCaptureSeq = seq;

    public void Start()
    {
        _source.BatchReady += OnBatch;
        _source.Faulted += msg => _fault = msg;
        _worker = Task.Run(ProcessLoop);
        _source.Start();
    }

    private void OnBatch(double[][] batch)
    {
        if (!_queue.TryAdd(batch)) { /* 队满则丢弃该批，避免阻塞采集线程 */ }
    }

    private void ProcessLoop()
    {
        foreach (var batch in _queue.GetConsumingEnumerable())
        {
            try
            {
                Interlocked.Add(ref _samples, batch.Length);
                foreach (var win in _agg.AddBatch(batch))
                    HandleWindow(win);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[处理] 窗处理失败: {ex.Message}");
            }
        }
    }

    private void HandleWindow(CompletedWindow win)
    {
        int ch = win.PerChannel.Length;
        var stats = new WindowStats[ch];
        // 常态：每通道特征落库
        for (int c = 0; c < ch; c++)
        {
            stats[c] = WindowStats.Compute(win.PerChannel[c]);
            _store.InsertFeature(win.StartTime, Session, c + 1, stats[c]);
        }

        // 事件触发：任一通道 RMS 越限 → 记事件 + 存全通道原始块
        bool eventTrig = false; int trigCh = -1; double trigVal = 0;
        if (_opt.EventEnabled && _opt.EventRmsThresholdG > 0)
        {
            for (int c = 0; c < ch; c++)
                if (stats[c].Rms > _opt.EventRmsThresholdG && stats[c].Rms > trigVal)
                { eventTrig = true; trigCh = c; trigVal = stats[c].Rms; }
        }
        if (eventTrig)
            StoreRaw(win, "threshold", trigCh + 1, trigVal);

        // 手动抓取：Web 端「抓取波形」请求
        int want = _pendingCaptureSeq;
        if (want != _captureDone)
        {
            StoreRaw(win, "manual", null, null);
            _captureDone = want;
            Console.WriteLine($"📸 已存原始块 (抓取 #{want}) session={Session}");
        }
    }

    private void StoreRaw(CompletedWindow win, string trigger, int? channel, double? metric)
    {
        long evId = _store.InsertEvent(win.StartTime, Session, trigger, channel, metric,
            _opt.Rate, 0, win.PerChannel.Length > 0 ? win.PerChannel[0].Length : 0);
        for (int c = 0; c < win.PerChannel.Length; c++)
            _store.InsertRawBlock(evId, c + 1, win.StartTime, _opt.Rate, win.PerChannel[c]);
    }

    public void Stop()
    {
        try { _source.Stop(); } catch { }
        try { _source.Dispose(); } catch { }
        _queue.CompleteAdding();
        try { _worker?.Wait(3000); } catch { }
    }

    private static IVibrationSource CreateSource(AcquisitionOptions opt) =>
        opt.Source.ToLowerInvariant() switch
        {
            "nidaq" =>
#if NIDAQ
                new NiDaqVibrationSource(opt),
#else
                throw new InvalidOperationException("未编入 NI 采集源。请以 NIDAQ 常量编译。"),
#endif
            _ => new SimulatedVibrationSource(opt),
        };
}
