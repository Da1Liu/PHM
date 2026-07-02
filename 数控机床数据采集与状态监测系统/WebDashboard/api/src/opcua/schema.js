import { query } from '../db.js';

// 建表语句对齐桌面端 PostgreSQL.cs 的 CreateOPCUA2 / CreateOPCUA3 / CreateMachineCoordinatesTable。
// 用 IF NOT EXISTS，幂等；与桌面程序共用同一组表（_OPCUA_2 / _OPCUA_3 / _OPCUA_new）。

const DDL_OPCUA2 = `
CREATE TABLE IF NOT EXISTS "_OPCUA_2" (
  id SERIAL PRIMARY KEY,
  time TIMESTAMP WITHOUT TIME ZONE,
  run_rate DOUBLE PRECISION,
  motor_speed DOUBLE PRECISION,
  spindle_current REAL,
  spindle_motor_temperature REAL,
  spindle_front_bearing_temperature REAL,
  spindle_rear_bearing_temperature REAL,
  spindle_tail_support_temperature REAL,
  reid INTEGER
);`;

const DDL_OPCUA3 = `
CREATE TABLE IF NOT EXISTS "_OPCUA_3" (
  id SERIAL PRIMARY KEY,
  time TIMESTAMP WITHOUT TIME ZONE,
  pit_oil_pump_pressure_monitor BOOLEAN,
  l2_oil_pump_pressure_monitor BOOLEAN,
  i16_oil_pump_pressure_monitor BOOLEAN,
  i24_oil_pump_pressure_monitor BOOLEAN,
  i243_oil_pump_pressure_monitor BOOLEAN,
  i161_oil_pump_pressure_monitor BOOLEAN,
  i162_oil_pump_pressure_monitor BOOLEAN,
  i241_oil_pump_pressure_monitor BOOLEAN,
  i242_oil_pump_pressure_monitor BOOLEAN,
  i234_oil_pump_pressure_monitor BOOLEAN,
  i235_oil_pump_pressure_monitor BOOLEAN,
  multi_head_pump_inlet_pressure BOOLEAN,
  multi_head_pump_outlet_pressure BOOLEAN,
  x1_axis_current REAL, x1_axis_temperature REAL, x1_axis_speed DOUBLE PRECISION,
  x2_axis_current REAL, x2_axis_temperature REAL, x2_axis_speed DOUBLE PRECISION,
  y1_axis_current REAL, y1_axis_temperature REAL, y1_axis_speed DOUBLE PRECISION,
  y2_axis_current REAL, y2_axis_temperature REAL, y2_axis_speed DOUBLE PRECISION,
  z_axis_current REAL,  z_axis_temperature REAL,  z_axis_speed DOUBLE PRECISION,
  w_axis_current REAL,  w_axis_temperature REAL,  w_axis_speed DOUBLE PRECISION,
  v_axis_current REAL,  v_axis_temperature REAL,  v_axis_speed DOUBLE PRECISION,
  b1_axis_current REAL, b1_axis_temperature REAL, b1_axis_speed DOUBLE PRECISION,
  b2_axis_current REAL, b2_axis_temperature REAL, b2_axis_speed DOUBLE PRECISION
);`;

const DDL_OPCUA_NEW = `
CREATE TABLE IF NOT EXISTS "_OPCUA_new" (
  id SERIAL PRIMARY KEY,
  x_mc DOUBLE PRECISION, y_mc DOUBLE PRECISION, z_mc DOUBLE PRECISION, w_mc DOUBLE PRECISION,
  sp_mc DOUBLE PRECISION, v_mc DOUBLE PRECISION, b_mc DOUBLE PRECISION, u_mc DOUBLE PRECISION,
  x_ac DOUBLE PRECISION, y_ac DOUBLE PRECISION, z_ac DOUBLE PRECISION, w_ac DOUBLE PRECISION,
  sp_ac DOUBLE PRECISION, v_ac DOUBLE PRECISION, b_ac DOUBLE PRECISION, u_ac DOUBLE PRECISION,
  time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);`;

export async function ensureOpcuaTables() {
  await query(DDL_OPCUA2);
  await query(DDL_OPCUA3);
  await query(DDL_OPCUA_NEW);
}
