"""Data ownership metadata for the current same-database phase.

No schema changes are implied here. The table names still point at the current
PostgreSQL layout; ownership describes the future migration direction.
"""

DATA_OWNERSHIP = {
    "phm_v2.machine": {
        "domain": "Cloud",
        "current": "shared PostgreSQL",
        "future": "Cloud DB authority, Edge cached mirror",
        "writes": "Cloud asset management; Edge may report discovered machines",
    },
    "phm_v2.signal": {
        "domain": "Shared",
        "current": "shared PostgreSQL",
        "future": "split by field ownership",
        "writes": "Cloud owns PHM semantics; Edge owns source_addr and collection enablement",
    },
    "phm_v2.acq_config": {
        "domain": "Edge",
        "current": "shared PostgreSQL",
        "future": "Edge Local DB authority, Cloud stores summary",
        "writes": "Edge owns acquisition config, control, heartbeat, and gateway endpoint",
    },
    "phm_v2.telemetry": {
        "domain": "Shared",
        "current": "shared PostgreSQL",
        "future": "Edge buffer -> Cloud DB via sync",
        "writes": "Edge/sync writes samples; Cloud reads and may score",
    },
    "phm_v2.vib_raw_blocks": {
        "domain": "Edge",
        "current": "shared PostgreSQL",
        "future": "Edge Local DB authority, Cloud receives selected blocks",
        "writes": "Edge collector writes raw waveform blocks",
    },
    "phm_v2.health_result": {
        "domain": "Cloud",
        "current": "shared PostgreSQL",
        "future": "Cloud DB authority; Edge may submit scored results",
        "writes": "score_runner or sync upsert",
    },
    "phm_v2.bridge_state": {
        "domain": "Edge",
        "current": "shared PostgreSQL",
        "future": "Edge Local DB sync/bridge watermark",
        "writes": "bridge or sync process only",
    },
    "public.vib_features": {
        "domain": "Edge",
        "current": "shared PostgreSQL public schema",
        "future": "Edge Local DB",
        "writes": "C# NI collector",
    },
    "public.vib_events": {
        "domain": "Edge",
        "current": "shared PostgreSQL public schema",
        "future": "Edge Local DB, selected event metadata synced",
        "writes": "C# NI collector",
    },
    "public._OPCUA_2/_OPCUA_3/_OPCUA_new": {
        "domain": "Edge",
        "current": "shared PostgreSQL public schema",
        "future": "Edge Local DB or direct telemetry writer",
        "writes": "Node OPC UA poller",
    },
    "public.app_config": {
        "domain": "Edge",
        "current": "legacy fallback",
        "future": "retired or Edge-only fallback",
        "writes": "legacy only; new code should use phm_v2.acq_config",
    },
}

