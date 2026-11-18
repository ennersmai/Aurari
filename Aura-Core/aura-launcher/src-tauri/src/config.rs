use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const CONFIG_VERSION: u32 = 2; // bumped: DockerConfig removed, SurrealDBConfig added

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuraConfig {
    pub config_version: u32,
    pub aura_app_path: PathBuf,
    /// Removed: `compose_file` — no longer needed in sovereign-native mode.
    #[serde(default)]
    pub services: ServicesConfig,
    #[serde(default)]
    pub ports: PortsConfig,
    #[serde(default)]
    pub health: HealthConfig,
    /// Replaces the old `docker` block.
    #[serde(default)]
    pub surrealdb: SurrealDBConfig,
    #[serde(default)]
    pub advanced: AdvancedConfig,
    #[serde(default)]
    pub tts: TtsConfig,
    #[serde(default)]
    pub inference: InferenceConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServicesConfig {
    pub database: String,
    pub backend: String,
    pub frontend: String,
}

impl Default for ServicesConfig {
    fn default() -> Self {
        Self {
            database: "aura-database".into(),
            backend: "aura-backend".into(),
            frontend: "aura-frontend".into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortsConfig {
    pub database: u16,
    pub backend: u16,
    pub frontend: u16,
}

impl Default for PortsConfig {
    fn default() -> Self {
        Self { database: 8000, backend: 8080, frontend: 3000 }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthConfig {
    pub backend_path: String,
    pub frontend_path: String,
    pub poll_interval_ms: u64,
    pub boot_timeout_secs: u64,
    pub probe_timeout_secs: u64,
}

impl Default for HealthConfig {
    fn default() -> Self {
        Self {
            backend_path: "/health".into(),
            frontend_path: "/".into(),
            poll_interval_ms: 1500,
            boot_timeout_secs: 180,
            probe_timeout_secs: 3,
        }
    }
}

// ---------------------------------------------------------------------------
// SurrealDB native config (replaces DockerConfig)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SurrealDBConfig {
    /// SurrealDB root username.
    #[serde(default = "default_surrealdb_user")]
    pub user: String,
    /// SurrealDB root password.
    #[serde(default = "default_surrealdb_pass")]
    pub pass: String,
    /// Path to the `surreal` binary.  If `None`, we rely on PATH.
    #[serde(default)]
    pub binary_path: Option<PathBuf>,
    /// Extra arguments passed to `surreal start`.
    #[serde(default)]
    pub extra_args: Vec<String>,
}

fn default_surrealdb_user() -> String {
    "root".into()
}

fn default_surrealdb_pass() -> String {
    "root".into()
}

impl Default for SurrealDBConfig {
    fn default() -> Self {
        Self {
            user: default_surrealdb_user(),
            pass: default_surrealdb_pass(),
            binary_path: None,
            extra_args: Vec::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// Advanced / TTS (unchanged from original)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AdvancedConfig {
    #[serde(default)]
    pub allow_alt_ports: bool,
    #[serde(default)]
    pub headless_persist_on_quit: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceConfig {
    /// Whether the launcher should spawn the SGLang inference server.
    /// Defaults to `false` so the launcher doesn't crash if no model is
    /// downloaded yet.
    #[serde(default)]
    pub enabled: bool,
    /// Path to the model directory passed as `--model-path` to SGLang.
    #[serde(default = "default_inference_model_path")]
    pub model_path: String,
}

fn default_inference_model_path() -> String {
    "./models/gemma2-27b".into()
}

impl Default for InferenceConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            model_path: default_inference_model_path(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TtsConfig {
    /// Whether the launcher should manage a bare-metal TTS process.
    #[serde(default)]
    pub enabled: bool,
    /// Absolute path to the TTS directory (contains the server script + venv/).
    #[serde(default)]
    pub tts_path: Option<PathBuf>,
    /// TCP port the TTS server listens on.
    #[serde(default = "default_tts_port")]
    pub port: u16,
    /// Model path passed as `--model_dir` to the server.
    #[serde(default = "default_model_dir")]
    pub model_dir: String,
    /// Relative path to the server script inside tts_path.
    /// Qwen3-TTS: `server.py`
    #[serde(default = "default_server_script")]
    pub server_script: String,
}

fn default_tts_port() -> u16 {
    50000
}

fn default_model_dir() -> String {
    "./Qwen3-TTS".into()
}

fn default_server_script() -> String {
    "server.py".into()
}

impl Default for TtsConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            tts_path: None,
            port: 50000,
            model_dir: default_model_dir(),
            server_script: default_server_script(),
        }
    }
}

// ---------------------------------------------------------------------------
// AuraConfig
// ---------------------------------------------------------------------------

impl Default for AuraConfig {
    fn default() -> Self {
        let aura_app_path = locate_aura_app().unwrap_or_else(|| PathBuf::from("."));
        Self {
            config_version: CONFIG_VERSION,
            aura_app_path,
            services: ServicesConfig::default(),
            ports: PortsConfig::default(),
            health: HealthConfig::default(),
            surrealdb: SurrealDBConfig::default(),
            advanced: AdvancedConfig::default(),
            tts: TtsConfig::default(),
            inference: InferenceConfig::default(),
        }
    }
}

impl AuraConfig {
    pub fn load_or_default() -> anyhow::Result<Self> {
        let path = config_path();
        if path.exists() {
            let raw = std::fs::read_to_string(&path)?;
            let cfg: Self = toml::from_str(&raw)?;
            if cfg.config_version != CONFIG_VERSION {
                anyhow::bail!(
                    "aura.config.toml has config_version={} but launcher expects {}",
                    cfg.config_version,
                    CONFIG_VERSION
                );
            }
            tracing::info!(path = %path.display(), "loaded aura.config.toml");
            Ok(cfg)
        } else {
            tracing::info!("no aura.config.toml found; using defaults");
            Ok(Self::default())
        }
    }

    /// Removed: `compose_file_path()` — no compose file in sovereign-native mode.

    pub fn env_file_path(&self) -> PathBuf {
        self.aura_app_path.join(".env")
    }

    pub fn backend_health_url(&self) -> String {
        format!("http://127.0.0.1:{}{}", self.ports.backend, self.health.backend_path)
    }

    pub fn frontend_url(&self) -> String {
        format!("http://127.0.0.1:{}{}", self.ports.frontend, self.health.frontend_path)
    }

    pub fn mission_control_url(&self) -> String {
        format!("http://127.0.0.1:{}/mission-control", self.ports.frontend)
    }

    pub fn ide_url(&self) -> String {
        format!("http://127.0.0.1:{}/ide", self.ports.frontend)
    }
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

pub fn config_path() -> PathBuf {
    if let Ok(env) = std::env::var("AURA_LAUNCHER_CONFIG") {
        return PathBuf::from(env);
    }
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));
    exe_dir.join("aura.config.toml")
}

pub fn log_dir() -> PathBuf {
    if let Some(local) = local_app_data() {
        local.join("Aura").join("logs")
    } else {
        PathBuf::from("./logs")
    }
}

fn local_app_data() -> Option<PathBuf> {
    std::env::var_os("LOCALAPPDATA").map(PathBuf::from)
}

/// Locate the `aura-app/` directory by walking up from the executable
/// and looking for `pyproject.toml` (the Python project manifest) instead
/// of the now-deleted `docker-compose.unified.yml`.
fn locate_aura_app() -> Option<PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))?;

    let mut cursor: Option<&Path> = Some(exe_dir.as_path());
    let mut hops = 0usize;
    while let Some(dir) = cursor {
        if hops > 8 {
            break;
        }
        for sub in ["aura-app", "Aura-Core/aura-app"] {
            let candidate = dir.join(sub);
            // Look for pyproject.toml as the canonical marker of the Python project.
            if candidate.join("pyproject.toml").exists() {
                return dunce::canonicalize(candidate).ok();
            }
        }
        cursor = dir.parent();
        hops += 1;
    }
    None
}
