// 验证脚本（不依赖数据库）：连接 OPC UA、批量读、按 config/transform 映射，打印三表行对象。
import { OPCUAClient, AttributeIds, MessageSecurityMode, SecurityPolicy, UserTokenType } from 'node-opcua';
import { OPCUA2_MAP, OPCUA3_MAP, OPCUA_NEW_MAP, deriveOpcua3, allNodeIds } from '../opcua/config.js';
import { coerce } from '../opcua/transform.js';

const endpoint = process.env.OPCUA_ENDPOINT || 'opc.tcp://localhost:49320';
const nodeIds = allNodeIds();
const idx = new Map(nodeIds.map((id, i) => [id, i]));

const client = OPCUAClient.create({
  endpointMustExist: false,
  securityMode: MessageSecurityMode.None,
  securityPolicy: SecurityPolicy.None,
  connectionStrategy: { maxRetry: 2, initialDelay: 500, maxDelay: 1500 },
});

const map = (m, raw) => Object.fromEntries(m.map((x) => [x.col, coerce(raw(x), x.type)]));

try {
  await client.connect(endpoint);
  const session = await client.createSession({ type: UserTokenType.Anonymous });
  console.log(`已连接 ${endpoint}，待读节点数: ${nodeIds.length}`);

  const results = await session.read(nodeIds.map((nodeId) => ({ nodeId, attributeId: AttributeIds.Value })));
  const goodCount = results.filter((r) => r.statusCode.isGood).length;
  console.log(`读取状态: ${goodCount}/${results.length} Good`);

  const raw = (m) => results[idx.get(m.node)]?.value?.value;
  const o2 = map(OPCUA2_MAP, raw);
  const o3 = map(OPCUA3_MAP, raw); Object.assign(o3, deriveOpcua3(o3));
  const onew = map(OPCUA_NEW_MAP, raw);

  console.log('\n_OPCUA_2:', JSON.stringify(o2, null, 0));
  console.log('\n_OPCUA_3 (片段):', JSON.stringify({
    pit_oil_pump_pressure_monitor: o3.pit_oil_pump_pressure_monitor,
    multi_head_pump_inlet_pressure: o3.multi_head_pump_inlet_pressure,
    x1_axis_current: o3.x1_axis_current,
    x1_axis_temperature: o3.x1_axis_temperature,
    b2_axis_speed: o3.b2_axis_speed,
  }));
  console.log('\n_OPCUA_new (片段):', JSON.stringify({ x_mc: onew.x_mc, u_ac: onew.u_ac }));
  console.log('\ndword2float 自检:', coerce(1109917696, 'dword2float'), '(期望 ≈42.0)');

  await session.close();
  await client.disconnect();
  console.log('\n✅ OPC UA 读取+映射+转换 验证通过');
  process.exit(0);
} catch (err) {
  console.error('❌ 验证失败:', err.message);
  try { await client.disconnect(); } catch {}
  process.exit(1);
}
