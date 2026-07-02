"""
采集层: 把 NC-Link 协议接到 phm_pipeline 的 CollectionRecord 契约上.

NC-Link 架构 (见 NC-Link应用开发指导手册):
  数控机床 --MQTT(EMQ:1883)--> API Server(Java jar, HTTP) <--HTTP-- 本采集层

本版只用 **寄存器轮询** 路径 (get_value), 与现场已验证的 CNCDataGet 一致:
  POST http://{host}:{port}/v1/{sn}/data/
  body {"operation":"get_value","items":[{"path":..,"index":..}]}
  resp {"status":"SUCCESS","code":0,"value":[[..]]}
当前 NC-Link 版本不支持采样波形订阅 (sample/sub), 故高频振动类特征不可得.

注意: model.json 是从机床 down 下来的模板, 其中接口并非全部有效 (随驱动版本不同),
故 channel_map 的候选必须 **先 probe 再用**, 不假设 model.json 里的都能取到.

模块:
  nclink_client  HTTP 客户端 (get_value/set_value/get_model/probe/ping) + Mock(离线演示)
  model_file     解析 model.json -> 候选寄存器清单 (供前端映射用)
  channel_map    NC-Link {path,index} -> PHM 通道/温度/工况 + 公式
  collector      轮询一个采集窗口 -> 一条 CollectionRecord
"""
