using System;
using Newtonsoft.Json.Linq;
using Npgsql;

namespace MachineCollector;

public sealed class CollectorControl
{
    private readonly string _conn;
    private readonly string _machineId;

    public CollectorControl(DatabaseOptions db)
    {
        _conn = db.ConnectionString;
        _machineId = ConfigStore.MachineId;
    }

    public void Ensure()
    {
        const string ddl = @"
CREATE SCHEMA IF NOT EXISTS phm_v2;
CREATE TABLE IF NOT EXISTS phm_v2.machine (
  machine_id TEXT PRIMARY KEY,
  cnc_system TEXT,
  model TEXT,
  current_epoch INT NOT NULL DEFAULT 1,
  note TEXT
);
CREATE TABLE IF NOT EXISTS phm_v2.acq_config (
  machine_id TEXT PRIMARY KEY REFERENCES phm_v2.machine(machine_id),
  data JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now()
);
INSERT INTO phm_v2.machine (machine_id, cnc_system, current_epoch, note)
VALUES (@m, 'siemens_840d', 1, 'edge gateway default machine')
ON CONFLICT (machine_id) DO NOTHING;
INSERT INTO phm_v2.acq_config (machine_id, data)
VALUES (@m, '{""acquisition"":{},""opcua"":{},""nclink"":{},""control"":{""ni_run"":false,""opcua_run"":false,""capture_seq"":0,""capture_done"":0}}'::jsonb)
ON CONFLICT (machine_id) DO NOTHING;";
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var cmd = new NpgsqlCommand(ddl, conn);
        cmd.Parameters.AddWithValue("m", _machineId);
        cmd.ExecuteNonQuery();
    }

    public sealed class Command
    {
        public bool NiRun;
        public int CaptureSeq;
    }

    public Command ReadCommand()
    {
        var root = ReadRoot();
        var ctrl = root["control"] as JObject ?? new JObject();
        return new Command
        {
            NiRun = ctrl.Value<bool?>("ni_run") ?? false,
            CaptureSeq = ctrl.Value<int?>("capture_seq") ?? 0,
        };
    }

    public void Heartbeat(string state, string message, long rows, double sps, string? session, int captureDone)
    {
        UpdateControl(ctrl =>
        {
            ctrl["ni_state"] = state;
            ctrl["ni_message"] = message ?? "";
            ctrl["ni_rows"] = rows;
            ctrl["ni_sps"] = sps;
            ctrl["session"] = session == null ? JValue.CreateNull() : JValue.FromObject(session);
            ctrl["capture_done"] = captureDone;
            ctrl["ni_heartbeat"] = DateTimeOffset.UtcNow.ToString("O");
        });
    }

    public void ClearRunFlag()
    {
        UpdateControl(ctrl => ctrl["ni_run"] = false);
    }

    private JObject ReadRoot()
    {
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var cmd = new NpgsqlCommand(
            "SELECT data::text FROM phm_v2.acq_config WHERE machine_id=@m", conn);
        cmd.Parameters.AddWithValue("m", _machineId);
        var json = cmd.ExecuteScalar() as string;
        return string.IsNullOrEmpty(json) ? new JObject() : JObject.Parse(json);
    }

    private void UpdateControl(Action<JObject> mutate)
    {
        using var conn = new NpgsqlConnection(_conn);
        conn.Open();
        using var tx = conn.BeginTransaction();
        JObject root;
        using (var read = new NpgsqlCommand(
            "SELECT data::text FROM phm_v2.acq_config WHERE machine_id=@m FOR UPDATE", conn, tx))
        {
            read.Parameters.AddWithValue("m", _machineId);
            var json = read.ExecuteScalar() as string;
            root = string.IsNullOrEmpty(json) ? new JObject() : JObject.Parse(json);
        }

        var ctrl = root["control"] as JObject;
        if (ctrl == null)
        {
            ctrl = new JObject();
            root["control"] = ctrl;
        }
        mutate(ctrl);

        using (var write = new NpgsqlCommand(
            "UPDATE phm_v2.acq_config SET data=CAST(@data AS jsonb), updated_at=now() WHERE machine_id=@m", conn, tx))
        {
            write.Parameters.AddWithValue("data", root.ToString(Newtonsoft.Json.Formatting.None));
            write.Parameters.AddWithValue("m", _machineId);
            write.ExecuteNonQuery();
        }
        tx.Commit();
    }
}
