// Data ownership metadata for the same-database transition phase.
// This does not change schema or queries; it documents future placement.
export const DATA_OWNERSHIP = Object.freeze({
  'phm_v2.acq_config': {
    domain: 'Edge',
    current: 'shared PostgreSQL',
    future: 'Edge Local DB authority, Cloud stores summary',
    writes: 'Edge UI, Node API, and C# collector',
  },
  'phm_v2.signal': {
    domain: 'Shared',
    current: 'shared PostgreSQL',
    future: 'field-level ownership',
    writes: 'Edge owns source_addr and enabled collection; Cloud owns PHM semantics',
  },
  'public.vib_features': {
    domain: 'Edge',
    current: 'shared PostgreSQL public schema',
    future: 'Edge Local DB',
    writes: 'C# NI collector',
  },
  'public.vib_events': {
    domain: 'Edge',
    current: 'shared PostgreSQL public schema',
    future: 'Edge Local DB, event metadata synced to Cloud',
    writes: 'C# NI collector',
  },
  'public.vib_raw_blocks': {
    domain: 'Edge',
    current: 'shared PostgreSQL public schema',
    future: 'Edge Local DB, selected blocks synced to Cloud',
    writes: 'C# NI collector',
  },
  'public._OPCUA_2/_OPCUA_3/_OPCUA_new': {
    domain: 'Edge',
    current: 'shared PostgreSQL public schema',
    future: 'Edge Local DB or direct telemetry writer',
    writes: 'Node OPC UA poller',
  },
  'public.app_config': {
    domain: 'Edge',
    current: 'legacy fallback',
    future: 'retired or Edge-only fallback',
    writes: 'legacy fallback only',
  },
});

