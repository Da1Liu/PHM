using System;
using System.Collections.Generic;

namespace MachineCollector;

/// <summary>一个特征窗的统计量（对应 vib_features 列）。</summary>
public struct WindowStats
{
    public int N;
    public double Mean, Rms, Peak, P2p, Std, Kurtosis, Crest;

    public static WindowStats Compute(double[] x)
    {
        int n = x.Length;
        double sum = 0, sumSq = 0, min = double.MaxValue, max = double.MinValue, peak = 0;
        for (int i = 0; i < n; i++)
        {
            double v = x[i];
            sum += v; sumSq += v * v;
            if (v < min) min = v;
            if (v > max) max = v;
            double a = Math.Abs(v);
            if (a > peak) peak = a;
        }
        double mean = n > 0 ? sum / n : 0;
        double rms = n > 0 ? Math.Sqrt(sumSq / n) : 0;
        double var = 0, m4 = 0;
        for (int i = 0; i < n; i++)
        {
            double d = x[i] - mean;
            var += d * d; m4 += d * d * d * d;
        }
        var = n > 0 ? var / n : 0;
        double std = Math.Sqrt(var);
        double kurt = (n > 0 && var > 1e-12) ? (m4 / n) / (var * var) : 0;
        double crest = rms > 1e-12 ? peak / rms : 0;
        return new WindowStats
        {
            N = n, Mean = mean, Rms = rms, Peak = peak,
            P2p = (n > 0 ? max - min : 0), Std = std, Kurtosis = kurt, Crest = crest,
        };
    }
}

/// <summary>一个完成的特征窗：起始时刻 + 各通道原始波形片段。</summary>
public sealed class CompletedWindow
{
    public DateTime StartTime;
    public double[][] PerChannel = Array.Empty<double[]>(); // [channel][sample]
}

/// <summary>
/// 把高频采样批次按窗切片：累满 windowSamples 即产出一个窗（各通道原始 + 可算特征）。
/// 各通道每批样本数相同，故同步填充。批小于窗时多批凑一窗；批跨窗也能处理。
/// </summary>
public sealed class WindowAggregator
{
    private readonly int _channels;
    private readonly int _window;
    private readonly double[][] _buf;   // [channel][window]
    private int _fill;
    private DateTime _windowStart = DateTime.Now;

    public WindowAggregator(int channels, int windowSamples)
    {
        _channels = channels;
        _window = Math.Max(1, windowSamples);
        _buf = new double[channels][];
        for (int c = 0; c < channels; c++) _buf[c] = new double[_window];
    }

    /// <summary>喂入一批 batch[sample][channel]，返回本批凑满的窗（可能 0..n 个）。</summary>
    public List<CompletedWindow> AddBatch(double[][] batch)
    {
        var done = new List<CompletedWindow>();
        int i = 0, len = batch.Length;
        while (i < len)
        {
            if (_fill == 0) _windowStart = DateTime.Now; // 窗起始时刻（近似）
            int take = Math.Min(_window - _fill, len - i);
            for (int k = 0; k < take; k++)
            {
                var row = batch[i + k];
                for (int c = 0; c < _channels; c++)
                    _buf[c][_fill + k] = c < row.Length ? row[c] : 0d;
            }
            _fill += take;
            i += take;

            if (_fill >= _window)
            {
                var per = new double[_channels][];
                for (int c = 0; c < _channels; c++)
                {
                    per[c] = new double[_window];
                    Array.Copy(_buf[c], per[c], _window);
                }
                done.Add(new CompletedWindow { StartTime = _windowStart, PerChannel = per });
                _fill = 0;
            }
        }
        return done;
    }
}
