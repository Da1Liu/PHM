// OPC UA 连接与节点映射。
// 迁移自桌面端 GlobalVariables.cs：包含两套地址 profile——
//   kepserver：虚拟环境/现场 KEPServer 标签名（GlobalVariables.cs 中“启用”的一套）
//   machine  ：真实机床 Siemens OPC UA 地址（GlobalVariables.cs 中“注释掉”的一套）
// 用环境变量 OPCUA_PROFILE=kepserver|machine 选择（默认 kepserver）。
// 列↔节点↔转换 统一一张表（对应 数据库对照.txt），改字段只改这里。

const NS_KEP = 'ns=2;s=通道 1.设备 1.';
const kep = (t) => NS_KEP + t;        // KEPServer 标签
const mc = (s) => 'ns=2;s=' + s;      // 机床绝对地址

// 连接默认值（取自环境变量；运行时实际配置来自 DB app_config，见 configStore.js）
export const connection = {
  endpoint: process.env.OPCUA_ENDPOINT || 'opc.tcp://localhost:49320',
  username: process.env.OPCUA_USER || 'OPCUA',
  password: process.env.OPCUA_PASSWORD || '123456',
  anonymous: (process.env.OPCUA_ANONYMOUS || 'false') === 'true',
  pollIntervalMs: Number(process.env.OPCUA_POLL_MS || 1000),
  profile: (process.env.OPCUA_PROFILE || 'kepserver').toLowerCase(),
};

// 进给各轴（顺序与 _OPCUA_3 建表一致）；machine 用驱动寄存器编号 u1..u9
const AXES = [
  ['x1', 'X1轴', 1], ['x2', 'X2轴', 2], ['y1', 'Y1轴', 3], ['y2', 'Y2轴', 4],
  ['z', 'Z轴', 5], ['w', 'W轴', 6], ['v', 'V轴', 7], ['b1', 'B1轴', 8], ['b2', 'B2轴', 9],
];

// ---- _OPCUA_2（主轴）----  [列, 类型, 中文名]
const O2_SCHEMA = [
  ['run_rate', 'double', '主轴运行倍率'],
  ['motor_speed', 'double', '主轴电机转速'],
  ['spindle_current', 'float', '主轴电流'],
  ['spindle_motor_temperature', 'float', '主轴电机温度'],
  ['spindle_front_bearing_temperature', 'dword2float', '主轴前轴承温度'],
  ['spindle_rear_bearing_temperature', 'dword2float', '主轴后轴承温度'],
  ['spindle_tail_support_temperature', 'dword2float', '主轴尾部支撑温度'],
];
const O2_NODES = {
  kepserver: ['标记 1', '标记 2', '主轴电流', '主轴温度', '标记 1', '主轴后轴承温度', '主轴尾部支撑温度'].map(kep),
  machine: [
    '/Channel/Spindle/actSpeed[u1,1]', '/DriveVsa/DC/R0021[u6]', '/DriveVsa/Drive/r0027[u8]',
    '/DriveVsa/Drive/R0035[u8]', '/Plc/DB182.DBD0', '/Plc/DB182.DBD4', '/Plc/DB182.DBD8',
  ].map(mc),
};
// ---- _OPCUA_3（油泵布尔 + 各轴）----
const OIL_COLS = [
  'pit_oil_pump_pressure_monitor', 'l2_oil_pump_pressure_monitor', 'i16_oil_pump_pressure_monitor',
  'i24_oil_pump_pressure_monitor', 'i243_oil_pump_pressure_monitor', 'i161_oil_pump_pressure_monitor',
  'i162_oil_pump_pressure_monitor', 'i241_oil_pump_pressure_monitor', 'i242_oil_pump_pressure_monitor',
  'i234_oil_pump_pressure_monitor', 'i235_oil_pump_pressure_monitor',
];
const OIL_LABELS = [
  '地坑油泵压力监测', 'L2油泵压力监测', '16油泵压力监测', '24油泵压力监测', '243油泵压力监测',
  '161油泵压力监测', '162油泵压力监测', '241油泵压力监测', '242油泵压力监测', '234油泵压力监测', '235油泵压力监测',
];
const OIL_NODES = {
  kepserver: ['地坑油泵压力监测', 'L2油泵压力监测', '16油泵压力监测', '24油泵压力监测', '243油泵压力监测',
    '161油泵压力监测', '162油泵压力监测', '241油泵压力监测', '242油泵压力监测', '234油泵压力监测', '235油泵压力监测'].map(kep),
  machine: ['/Plc/I36.0', '/Plc/I17.2', '/Plc/I16.0', '/Plc/I24.0', '/Plc/I24.3', '/Plc/I16.1',
    '/Plc/I16.2', '/Plc/I24.1', '/Plc/I24.2', '/Plc/I23.4', '/Plc/I23.5'].map(mc),
};

function axisNodes(profile, key, prefix, u, metric) {
  if (profile === 'machine') {
    if (metric === 'current') return mc(`/DriveVsa/Drive/r0027[u${u}]`);
    if (metric === 'temperature') return mc(`/DriveVsa/Drive/R0035[u${u}]`);
    return mc(`/Nck/MachineAxis/actFeedRate[u${u}]`); // speed
  }
  // kepserver：速度复用温度节点（与桌面端虚拟环境一致）
  if (metric === 'current') return kep(`${prefix}电流`);
  return kep(`${prefix}温度`);
}

// ---- _OPCUA_new（坐标）----
const COORD_COLS = [
  'x_mc', 'y_mc', 'z_mc', 'w_mc', 'sp_mc', 'v_mc', 'b_mc', 'u_mc',
  'x_ac', 'y_ac', 'z_ac', 'w_ac', 'sp_ac', 'v_ac', 'b_ac', 'u_ac',
];
const COORD_LABELS = [
  'X 机械坐标', 'Y 机械坐标', 'Z 机械坐标', 'W 机械坐标', 'SP 机械坐标', 'V 机械坐标', 'B 机械坐标', 'U 机械坐标',
  'X 绝对坐标', 'Y 绝对坐标', 'Z 绝对坐标', 'W 绝对坐标', 'SP 绝对坐标', 'V 绝对坐标', 'B 绝对坐标', 'U 绝对坐标',
];
const COORD_NODES = {
  kepserver: COORD_COLS.map(() => kep('X1轴温度')), // 虚拟环境占位（与桌面端一致）
  machine: [
    // 机械坐标（MachineAxis）u1,1..u1,7 + u1,9
    ...[1, 2, 3, 4, 5, 6, 7, 9].map((i) => mc(`/Channel/MachineAxis/actToolBasePos[u1,${i}]`)),
    // 绝对坐标（GeometricAxis）
    ...[1, 2, 3, 4, 5, 6, 7, 9].map((i) => mc(`/Channel/GeometricAxis/actToolBasePos[u1,${i}]`)),
  ],
};
// 按 profile 构建三张表的 列↔节点↔类型 映射 + 去重节点全集。
export function buildOpcua(profile) {
  const p = (profile || 'kepserver').toLowerCase() === 'machine' ? 'machine' : 'kepserver';
  const opcua2 = O2_SCHEMA.map(([col, type, label], i) => ({ col, type, label, node: O2_NODES[p][i] }));
  const opcua3 = [
    ...OIL_COLS.map((col, i) => ({ col, node: OIL_NODES[p][i], type: 'bool', label: OIL_LABELS[i] })),
    ...AXES.flatMap(([key, prefix, u]) => [
      { col: `${key}_axis_current`, node: axisNodes(p, key, prefix, u, 'current'), type: 'float', label: `${prefix} 电流` },
      { col: `${key}_axis_temperature`, node: axisNodes(p, key, prefix, u, 'temperature'), type: 'float', label: `${prefix} 温度` },
      { col: `${key}_axis_speed`, node: axisNodes(p, key, prefix, u, 'speed'), type: 'double', label: `${prefix} 速度` },
    ]),
  ];
  const opcuaNew = COORD_COLS.map((col, i) => ({ col, node: COORD_NODES[p][i], type: 'double', label: COORD_LABELS[i] }));
  const nodeSet = new Set();
  [...opcua2, ...opcua3, ...opcuaNew].forEach((m) => nodeSet.add(m.node));
  return { profile: p, OPCUA2_MAP: opcua2, OPCUA3_MAP: opcua3, OPCUA_NEW_MAP: opcuaNew, allNodeIds: [...nodeSet] };
}

// 兼容旧导入（按环境 profile 构建一份）
const _envMaps = buildOpcua(connection.profile);
export const OPCUA2_MAP = _envMaps.OPCUA2_MAP;
export const OPCUA3_MAP = _envMaps.OPCUA3_MAP;
export const OPCUA_NEW_MAP = _envMaps.OPCUA_NEW_MAP;
export function allNodeIds() { return _envMaps.allNodeIds; }

// _OPCUA_3 中由多个油泵量“与”运算得到的派生列（不对应任何 OPC UA 节点）
export const DERIVED_OPCUA3 = [
  { col: 'multi_head_pump_inlet_pressure', label: '多头泵进口压力（派生）' },
  { col: 'multi_head_pump_outlet_pressure', label: '多头泵出口压力（派生）' },
];

// 派生布尔量（对应 Form2 的 multi_head_pump_inlet/outlet）
export function deriveOpcua3(values) {
  const v = (c) => values[c];
  return {
    multi_head_pump_inlet_pressure:
      v('i16_oil_pump_pressure_monitor') && v('i24_oil_pump_pressure_monitor') && v('i243_oil_pump_pressure_monitor'),
    multi_head_pump_outlet_pressure:
      v('i161_oil_pump_pressure_monitor') && v('i162_oil_pump_pressure_monitor') &&
      v('i241_oil_pump_pressure_monitor') && v('i242_oil_pump_pressure_monitor') &&
      v('i234_oil_pump_pressure_monitor') && v('i235_oil_pump_pressure_monitor'),
  };
}
