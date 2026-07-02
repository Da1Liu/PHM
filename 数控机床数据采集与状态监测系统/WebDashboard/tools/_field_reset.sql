-- 验证后回到现场就绪状态：清模拟测试数据、采集源设回 nidaq、OPC UA 关闭、控制行复位。
-- 注意：保留用户选择留存的部分采集表 _tb_field_2026_06_18_14_31_51_main。
TRUNCATE vib_raw_blocks, vib_events, vib_features RESTART IDENTITY;
UPDATE collector_control
   SET ni_run = false, capture_seq = 0, capture_done = 0, ni_state = 'idle', ni_message = ''
 WHERE id = 1;
UPDATE app_config
   SET data = jsonb_set(
               jsonb_set(data, '{acquisition,source}', '"nidaq"'::jsonb),
               '{opcua,enabled}', 'false'::jsonb)
 WHERE id = 1;
SELECT data->'acquisition'->>'source' AS source,
       data->'opcua'->>'enabled'      AS opcua_enabled
  FROM app_config WHERE id = 1;
SELECT 'vib_features' AS t, count(*) FROM vib_features
UNION ALL SELECT 'vib_events', count(*) FROM vib_events
UNION ALL SELECT 'vib_raw_blocks', count(*) FROM vib_raw_blocks;
