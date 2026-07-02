// 值转换，对应 Form2 里的手工转型（.ToFloat()/.ToDouble()/.ToBool()/DWordToDouble）。

// 把 uint32 的位重解释为 float32 —— 对应 C# Form2.DWordToDouble：
//   byte[] bytes = BitConverter.GetBytes(dwordValue);
//   return BitConverter.ToSingle(bytes, 0);
export function dwordToFloat(dwordValue) {
  const u = Number(dwordValue) >>> 0; // 转无符号 32 位
  const buf = Buffer.alloc(4);
  buf.writeUInt32LE(u, 0);
  return buf.readFloatLE(0);
}

export function coerce(raw, type) {
  if (raw == null) return null;
  switch (type) {
    case 'bool':
      if (typeof raw === 'boolean') return raw;
      return String(raw).toLowerCase() === 'true' || Number(raw) === 1;
    case 'float':
    case 'double': {
      const num = typeof raw === 'number' ? raw : Number(raw);
      return Number.isFinite(num) ? num : null;
    }
    case 'dword2float': {
      const u = typeof raw === 'number' ? raw : Number(raw);
      if (!Number.isFinite(u)) return null;
      return dwordToFloat(u);
    }
    default:
      return raw;
  }
}
