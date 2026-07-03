import 'dotenv/config';
import pg from 'pg';
import { DATA_OWNERSHIP } from './domain/ownership.js';

const { Pool } = pg;

// Ownership metadata only. Queries still use the current same PostgreSQL DB.
export const DB_OWNERSHIP = DATA_OWNERSHIP;

// pg 默认把 BIGINT/NUMERIC 解析为字符串以防精度丢失；本看板的列均为
// REAL / DOUBLE PRECISION / INT，统一交给默认解析即可（DOUBLE 走 float8 -> number）。
export const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: Number(process.env.PGPORT || 5432),
  database: process.env.PGDATABASE || 'vibration_db',
  user: process.env.PGUSER || 'postgres',
  password: process.env.PGPASSWORD || '123456',
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

pool.on('error', (err) => {
  console.error('[pg pool] 空闲连接异常:', err.message);
});

export async function query(text, params) {
  const client = await pool.connect();
  try {
    return await client.query(text, params);
  } finally {
    client.release();
  }
}

