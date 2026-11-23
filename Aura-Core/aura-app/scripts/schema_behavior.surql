-- Behaviour schema (B1-01). Idempotent.
nUSE NS aura DB main;

DEFINE TABLE IF NOT EXISTS autonomy_control SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS level ON autonomy_control TYPE string;
DEFINE FIELD IF NOT EXISTS muted_kinds ON autonomy_control TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS killed ON autonomy_control TYPE bool DEFAULT false;
DEFINE FIELD IF NOT EXISTS killed_at ON autonomy_control TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS updated_at ON autonomy_control TYPE datetime;

DEFINE TABLE IF NOT EXISTS autonomy_trace SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS source ON autonomy_trace TYPE string;
DEFINE FIELD IF NOT EXISTS action ON autonomy_trace TYPE string;
DEFINE FIELD IF NOT EXISTS why ON autonomy_trace TYPE string;
DEFINE FIELD IF NOT EXISTS cost ON autonomy_trace TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD IF NOT EXISTS refs ON autonomy_trace TYPE array DEFAULT [];
DEFINE FIELD IF NOT EXISTS at ON autonomy_trace TYPE datetime;
DEFINE FIELD IF NOT EXISTS allowed ON autonomy_trace TYPE bool;
DEFINE INDEX IF NOT EXISTS autonomy_trace_at ON autonomy_trace FIELDS at;
