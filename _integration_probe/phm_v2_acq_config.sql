-- phm_v2 閲囬泦閰嶇疆/鎺у埗 (per-machine). 缁撴瀯瀵归綈绾緽 app_config (configStore.js DEFAULTS):
--   data = { acquisition:{...}, opcua:{...}, nclink:{...}, control:{...} }
SET search_path TO phm_v2;

CREATE TABLE IF NOT EXISTS acq_config (
  machine_id TEXT PRIMARY KEY REFERENCES machine(machine_id),
  data       JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 棣栧彴: 鍚屾绾緽 鐪熷疄榛樿 (configStore.js + opcua/config.js)
INSERT INTO acq_config (machine_id, data) VALUES ('FIELD_2026_06_18', '{
  "edge": {"mode": "edge_gateway", "gatewayId": "FIELD_2026_06_18", "baseUrl": "http://localhost:4000"},
  "acquisition": {
    "source": "simulated",
    "rate": 25600,
    "samplesPerChannel": 1600,
    "inputBufferSize": 300000,
    "tableBaseName": "tb_dev",
    "featureWindowSamples": 0,
    "eventEnabled": false,
    "eventRmsThresholdG": 0,
    "channels": [
      {"physicalChannel": "cDAQ1Mod4/ai0", "sensitivityMvPerG": 98.94},
      {"physicalChannel": "cDAQ1Mod4/ai1", "sensitivityMvPerG": 98.94},
      {"physicalChannel": "cDAQ1Mod4/ai2", "sensitivityMvPerG": 98.94},
      {"physicalChannel": "cDAQ1Mod4/ai3", "sensitivityMvPerG": 98.94}
    ]
  },
  "opcua": {
    "enabled": false,
    "profile": "kepserver",
    "endpoint": "opc.tcp://localhost:49320",
    "anonymous": false,
    "username": "OPCUA",
    "password": "123456",
    "pollIntervalMs": 1000
  },
  "nclink": {"host": "", "port": 8080, "sn": ""},
  "control": {"ni_run": false, "opcua_run": false, "capture_seq": 0, "capture_done": 0, "ni_state": "idle", "ni_message": "", "ni_heartbeat": null, "ni_rows": 0, "ni_sps": 0, "session": null}
}'::jsonb)
ON CONFLICT (machine_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now();



