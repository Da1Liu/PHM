import { getConfig, saveConfig } from './configStore.js';

export async function ensureControlTable() {
  const cfg = await getConfig();
  await saveConfig({ control: cfg.control || {} });
}

function daemonAlive(heartbeat) {
  const hb = heartbeat ? new Date(heartbeat).getTime() : 0;
  return hb > 0 && Date.now() - hb < 10000;
}

export async function getNiStatus() {
  const cfg = await getConfig();
  const c = cfg.control || {};
  return {
    exists: true,
    daemonAlive: daemonAlive(c.ni_heartbeat),
    ni_run: !!c.ni_run,
    ni_state: c.ni_state || 'unknown',
    ni_message: c.ni_message || '',
    ni_heartbeat: c.ni_heartbeat || null,
    ni_rows: Number(c.ni_rows || 0),
    ni_sps: Number(c.ni_sps || 0),
    session: c.session || c.current_table || null,
    capture_seq: Number(c.capture_seq || 0),
    capture_done: Number(c.capture_done || 0),
  };
}

export async function setNiRun(run) {
  await saveConfig({ control: { ni_run: !!run } });
  return getNiStatus();
}

export async function requestCapture() {
  const cfg = await getConfig();
  const seq = Number(cfg.control?.capture_seq || 0) + 1;
  await saveConfig({ control: { capture_seq: seq } });
  return seq;
}
