using System;
using Newtonsoft.Json;
using Npgsql;

namespace MachineCollector;

public static class ConfigStore
{
    public static string MachineId =>
        Environment.GetEnvironmentVariable("EDGE_MACHINE_ID") ?? "FIELD_2026_06_18";

    public static AcquisitionOptions? TryLoadAcquisition(DatabaseOptions db)
    {
        using var conn = new NpgsqlConnection(db.ConnectionString);
        conn.Open();

        var json = TryReadAcqConfig(conn);
        if (string.IsNullOrEmpty(json)) json = TryReadLegacyConfig(conn);
        if (string.IsNullOrEmpty(json)) return null;

        var root = JsonConvert.DeserializeObject<DbConfigRoot>(json);
        return root?.Acquisition;
    }

    private static string? TryReadAcqConfig(NpgsqlConnection conn)
    {
        try
        {
            using var cmd = new NpgsqlCommand(
                "SELECT data::text FROM phm_v2.acq_config WHERE machine_id=@m", conn);
            cmd.Parameters.AddWithValue("m", MachineId);
            return cmd.ExecuteScalar() as string;
        }
        catch (PostgresException)
        {
            return null;
        }
    }

    private static string? TryReadLegacyConfig(NpgsqlConnection conn)
    {
        using (var check = new NpgsqlCommand("SELECT to_regclass('public.app_config')::text", conn))
        {
            var reg = check.ExecuteScalar();
            if (reg == null || reg is DBNull) return null;
        }

        using var cmd = new NpgsqlCommand("SELECT data::text FROM app_config WHERE id=1", conn);
        return cmd.ExecuteScalar() as string;
    }

    private sealed class DbConfigRoot
    {
        public AcquisitionOptions? Acquisition { get; set; }
    }
}
