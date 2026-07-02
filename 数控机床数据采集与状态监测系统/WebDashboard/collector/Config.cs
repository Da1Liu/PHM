using System.Collections.Generic;

namespace MachineCollector;

/// <summary>appsettings.json 根对象（Newtonsoft 反序列化）。</summary>
public sealed class AppSettings
{
    public DatabaseOptions Database { get; set; } = new();
    public AcquisitionOptions Acquisition { get; set; } = new();
}

public sealed class DatabaseOptions
{
    public string Host { get; set; } = "localhost";
    public int Port { get; set; } = 5432;
    public string Database { get; set; } = "vibration_db";
    public string Username { get; set; } = "postgres";
    public string Password { get; set; } = "";

    public string ConnectionString =>
        $"Host={Host};Port={Port};Database={Database};Username={Username};Password={Password}";
}

public sealed class ChannelOptions
{
    public string PhysicalChannel { get; set; } = "";
    public double SensitivityMvPerG { get; set; } = 98.94;
}

public sealed class AcquisitionOptions
{
    // simulated | nidaq
    public string Source { get; set; } = "simulated";
    public int Rate { get; set; } = 25600;
    public int SamplesPerChannel { get; set; } = 1600;
    public List<ChannelOptions> Channels { get; set; } = new();
    public int InputBufferSize { get; set; } = 300000;
    public string TableBaseName { get; set; } = "tb_dev";

    // —— 落盘策略（C 特征 + D 事件触发原始 + A 块压缩）——
    // 常态只存每窗特征；原始波形仅在「手动抓取」或「事件触发」时存为 float32 块。
    /// <summary>特征窗样本数（每通道）。0 = 用采样率（1 秒一窗）。</summary>
    public int FeatureWindowSamples { get; set; } = 0;
    /// <summary>是否启用事件触发原始存储（按 RMS 阈值）。现场基线未知时默认关。</summary>
    public bool EventEnabled { get; set; } = false;
    /// <summary>事件触发的 RMS 阈值（g）。某通道窗 RMS 超过即记一次事件并存原始块。</summary>
    public double EventRmsThresholdG { get; set; } = 0;

    public int ChannelCount => Channels.Count;
    public int WindowSamples => FeatureWindowSamples > 0 ? FeatureWindowSamples : Rate;
}
