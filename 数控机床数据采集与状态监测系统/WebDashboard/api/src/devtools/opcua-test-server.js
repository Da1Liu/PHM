// 本地 OPC UA 测试 Server，用于无真实机床/KEPServer 时验证后端轮询。
// 暴露与 GlobalVariables.cs 虚拟环境同名的标签（ns=2;s=通道 1.设备 1.xxx），值随时间变化。
// 运行：node src/devtools/opcua-test-server.js  （默认 opc.tcp://localhost:49320）
import {
  OPCUAServer, Variant, DataType, StatusCodes,
} from 'node-opcua';

const PORT = Number(process.env.TEST_OPCUA_PORT || 49320);

// 要暴露的标签：名称 -> { dataType, gen(t) }
const t0 = Date.now();
const sec = () => (Date.now() - t0) / 1000;

const FLOAT_TAGS = [
  '主轴电流', '主轴温度', '主轴后轴承温度', '主轴尾部支撑温度',
  'X1轴电流', 'X1轴温度', 'X2轴电流', 'X2轴温度', 'Y1轴电流', 'Y1轴温度',
  'Y2轴电流', 'Y2轴温度', 'Z轴电流', 'Z轴温度', 'W轴电流', 'W轴温度',
  'V轴电流', 'V轴温度', 'B1轴电流', 'B1轴温度', 'B2轴电流', 'B2轴温度',
];
const DOUBLE_TAGS = ['标记 1', '标记 2'];
const BOOL_TAGS = [
  '地坑油泵压力监测', 'L2油泵压力监测', '16油泵压力监测', '24油泵压力监测',
  '243油泵压力监测', '161油泵压力监测', '162油泵压力监测', '241油泵压力监测',
  '242油泵压力监测', '234油泵压力监测', '235油泵压力监测',
];

(async () => {
  const server = new OPCUAServer({
    port: PORT,
    resourcePath: '',
    buildInfo: { productName: 'MachineTestServer', buildNumber: '1', buildDate: new Date() },
  });

  await server.initialize();
  const addressSpace = server.engine.addressSpace;
  const ns = addressSpace.getOwnNamespace(); // namespaceIndex = 1 默认；但客户端用 ns=2

  // 客户端节点写死 ns=2，这里需要 namespaceIndex 与之匹配。
  // getOwnNamespace 通常是 index=1。再注册一个命名空间占到 index=2。
  const ns2 = addressSpace.registerNamespace('urn:machine-test');

  const device = ns2.addObject({
    organizedBy: addressSpace.rootFolder.objects,
    browseName: '设备 1',
  });

  const addVar = (tag, dataType, gen) => {
    ns2.addVariable({
      componentOf: device,
      nodeId: `s=通道 1.设备 1.${tag}`,
      browseName: tag,
      dataType,
      value: {
        get: () => new Variant({ dataType, value: gen() }),
      },
    });
  };

  FLOAT_TAGS.forEach((tag, i) =>
    addVar(tag, DataType.Float, () => 20 + 10 * Math.sin(sec() / 5 + i) + Math.random()));
  DOUBLE_TAGS.forEach((tag, i) =>
    addVar(tag, DataType.Double, () => 100 + 50 * Math.sin(sec() / 7 + i)));
  BOOL_TAGS.forEach((tag, i) =>
    addVar(tag, DataType.Boolean, () => Math.floor(sec() / (3 + i)) % 2 === 0));

  await server.start();
  const endpoint = server.endpoints[0].endpointDescriptions()[0].endpointUrl;
  console.log(`测试 OPC UA Server 已启动: ${endpoint}`);
  console.log(`命名空间 index=2 (ns=2)，标签前缀 "通道 1.设备 1."；匿名登录。Ctrl+C 退出。`);
})();
