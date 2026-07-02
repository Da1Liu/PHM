using System;
using Npgsql;
using NpgsqlTypes;

namespace MachineCollector;

/// <summary>
/// 落盘策略存储层（替代旧的"一采样点一行"_main 大表）：
///  C 特征：每窗每通道一行统计量 → vib_features（常态、极小）。
///  D 事件：越限触发记一次 → vib_events；A 块：原始波形按通道存 float32 字节块 → vib_raw_blocks。
/// 手动抓取也走 vib_raw_blocks（event_id 为空）。块用 bytea，PG TOAST 自带压缩。
/// </summary>
public sealed class VibStore
{
    private readonly string _conn;
    public VibStore(DatabaseOptions db) => _conn = db.ConnectionString;

    /// <summary>幂等建表（表通常已由建库脚本建好；这里兜底，保证单机也能跑）。</summary>
    public void EnsureTables()
    {
        const string ddl = @"
CREATE TABLE IF NOT EXISTS vib_features (
  id BIGSERIAL PRIMARY KEY,
  ""time"" TIMESTAMPTZ NOT NULL,
  session TEXT NOT NULL,
  channel INT NOT NULL,
  n_samples INT,
  mean DOUBLE PRECISION, rms DOUBLE PRECISION, peak DOUBLE PRECISION,
  p2p DOUBLE PRECISION, std DOUBLE PRECISION, kurtosis DOUBLE PRECISION, crest DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_vib_features_time ON vib_features(""time"");
CREATE INDEX IF NOT EXISTS ix_vib_features_ch_time ON vib_features(channel, ""time"");

CREATE TABLE IF NOT EXISTS vib_events (
  id BIGSERIAL PRIMARY KEY,
  ""time"" TIMESTAMPTZ NOT NULL,
  session TEXT, ""trigger"" TEXT, channel INT,
  metric_value DOUBLE PRECISION, rate INT, pre_samples INT, post_samples INT
);
CREATE INDEX IF NOT EXISTS ix_vib_events_time ON vib_events(""time"");

CREATE TABLE IF NOT EXISTS vib_raw_blocks (
  id BIGSERIAL PRIMARY KEY,
  event_id BIGINT REFERENCES vib_events(id) ON DELETE CASCADE,
  channel INT NOT NULL,
  time_start TIMESTAMPTZ NOT NULL,
  rate INT NOT NULL,
  n_samples INT NOT NULL,
  data BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vib_raw_blocks_event ON vib_raw_blocks(event_id);";
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var cmd = new NpgsqlCommand(ddl, conn);
        cmd.ExecuteNonQuery();
    }

    public void InsertFeature(DateTime time, string session, int channel, WindowStats s)
    {
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var cmd = new NpgsqlCommand(@"
INSERT INTO vib_features (""time"", session, channel, n_samples, mean, rms, peak, p2p, std, kurtosis, crest)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)", conn);
        cmd.Parameters.AddWithValue(time);
        cmd.Parameters.AddWithValue(session);
        cmd.Parameters.AddWithValue(channel);
        cmd.Parameters.AddWithValue(s.N);
        cmd.Parameters.AddWithValue(s.Mean);
        cmd.Parameters.AddWithValue(s.Rms);
        cmd.Parameters.AddWithValue(s.Peak);
        cmd.Parameters.AddWithValue(s.P2p);
        cmd.Parameters.AddWithValue(s.Std);
        cmd.Parameters.AddWithValue(s.Kurtosis);
        cmd.Parameters.AddWithValue(s.Crest);
        cmd.ExecuteNonQuery();
    }

    /// <summary>记一次事件，返回事件 id（手动抓取传 trigger='manual'、channel/metric 可空）。</summary>
    public long InsertEvent(DateTime time, string session, string trigger, int? channel, double? metric, int rate, int preSamples, int postSamples)
    {
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var cmd = new NpgsqlCommand(@"
INSERT INTO vib_events (""time"", session, ""trigger"", channel, metric_value, rate, pre_samples, post_samples)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id", conn);
        cmd.Parameters.AddWithValue(time);
        cmd.Parameters.AddWithValue(session);
        cmd.Parameters.AddWithValue(trigger);
        cmd.Parameters.AddWithValue((object?)channel ?? DBNull.Value);
        cmd.Parameters.AddWithValue((object?)metric ?? DBNull.Value);
        cmd.Parameters.AddWithValue(rate);
        cmd.Parameters.AddWithValue(preSamples);
        cmd.Parameters.AddWithValue(postSamples);
        return (long)cmd.ExecuteScalar()!;
    }

    /// <summary>存一个通道的原始波形块（float32 小端字节）。</summary>
    public void InsertRawBlock(long? eventId, int channel, DateTime timeStart, int rate, double[] samples)
    {
        var bytes = new byte[samples.Length * 4];
        Buffer.BlockCopy(ToFloat(samples), 0, bytes, 0, bytes.Length);
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var cmd = new NpgsqlCommand(@"
INSERT INTO vib_raw_blocks (event_id, channel, time_start, rate, n_samples, data)
VALUES ($1,$2,$3,$4,$5,$6)", conn);
        cmd.Parameters.AddWithValue((object?)eventId ?? DBNull.Value);
        cmd.Parameters.AddWithValue(channel);
        cmd.Parameters.AddWithValue(timeStart);
        cmd.Parameters.AddWithValue(rate);
        cmd.Parameters.AddWithValue(samples.Length);
        cmd.Parameters.Add(new NpgsqlParameter { Value = bytes, NpgsqlDbType = NpgsqlDbType.Bytea });
        cmd.ExecuteNonQuery();
    }

    private static float[] ToFloat(double[] d)
    {
        var f = new float[d.Length];
        for (int i = 0; i < d.Length; i++) f[i] = (float)d[i];
        return f;
    }
}
