//! Aura Launcher — sovereign-native Windows shell that spawns SurrealDB and
//! the Python AI Engine (Uvicorn) as bare-metal OS child processes with
//! headless execution and log streaming to the Tauri UI.  No Docker, no
//! containers, no black boxes.
//!
//! See V1PRD.md §3 for the original product spec (now adapted for native mode).

pub mod commands;
pub mod config;
pub mod health;
pub mod log_server;
pub mod process_bridge;
pub mod state;
pub mod tray;
pub mod tts_supervisor;

use std::sync::Arc;

use parking_lot::RwLock;
use tauri_plugin_notification::NotificationExt;
use tracing_subscriber::EnvFilter;

pub use config::AuraConfig;
pub use process_bridge::ProcessBridge;
pub use state::{LauncherState, StateMachine};
pub use tts_supervisor::TtsSupervisor;

pub type SharedState = Arc<RwLock<StateMachine>>;
pub type SharedTts = Arc<TtsSupervisor>;
pub type SharedBridge = Arc<ProcessBridge>;

pub fn run() {
    init_logging();
    log_server::start();

    let config = AuraConfig::load_or_default().unwrap_or_else(|e| {
        tracing::error!(error = %e, "failed to load config; using defaults");
        AuraConfig::default()
    });

    let state: SharedState = Arc::new(RwLock::new(StateMachine::new()));
    let tts: SharedTts = Arc::new(TtsSupervisor::new());
    let bridge: SharedBridge = Arc::new(ProcessBridge::new());

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(config.clone())
        .manage(state.clone())
        .manage(tts.clone())
        .manage(bridge.clone())
        .invoke_handler(tauri::generate_handler![
            commands::get_status,
            commands::start_aura,
            commands::stop_aura,
            commands::restart_backend,
            commands::open_url,
            commands::save_env,
        ])
        .setup({
            let state = state.clone();
            let config = config.clone();
            let tts = tts.clone();
            let bridge = bridge.clone();
            move |app| {
                tray::setup(app.handle(), state.clone())?;

                let app_handle = app.handle().clone();
                let state_clone = state.clone();
                let config_clone = config.clone();
                let tts_clone = tts.clone();
                let bridge_clone = bridge.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = boot_pipeline(app_handle, state_clone, config_clone, tts_clone, bridge_clone).await {
                        tracing::error!(error = %e, "boot pipeline failed");
                    }
                });
                Ok(())
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build Aura launcher")
        .run(|_app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                // Tray app: don't exit when last window closes; only exit on explicit Quit.
                api.prevent_exit();
            }
        });
}

/// Sovereign-native boot pipeline.
///
/// 1. Spawn SurrealDB headlessly.
/// 2. Poll SurrealDB's TCP port until it is actually listening.
/// 3. Spawn the Python Uvicorn backend headlessly *after* SurrealDB is ready.
/// 4. Start log streaming for both services.
/// 5. (Optional) Start bare-metal Qwen3-TTS via venv.
/// 6. Health-check the backend and frontend.
/// 7. Transition to `Ready` and open Mission Control, then start liveness watchdog.
pub async fn boot_pipeline<R: tauri::Runtime>(
    app: tauri::AppHandle<R>,
    state: SharedState,
    config: AuraConfig,
    tts: SharedTts,
    bridge: SharedBridge,
) -> anyhow::Result<()> {
    use health::HealthChecker;

    // ------------------------------------------------------------------
    // Phase 1 — Spawn SurrealDB
    // ------------------------------------------------------------------
    state.write().transition(LauncherState::ServicesStarting);
    tray::refresh(&app, state.read().current())?;

    tracing::info!(
        user = %config.surrealdb.user,
        port = %config.ports.database,
        "spawning SurrealDB natively"
    );

    if let Err(e) = bridge.spawn_surrealdb(
        &config.surrealdb.user,
        &config.surrealdb.pass,
        config.ports.database,
    ) {
        let reason = format!("failed to spawn SurrealDB: {e}");
        state.write().transition(LauncherState::Failed { reason: reason.clone() });
        tray::refresh(&app, state.read().current())?;
        return Err(anyhow::anyhow!(reason));
    }

    // ------------------------------------------------------------------
    // Phase 1.5 — Deterministic SurrealDB health gate
    // ------------------------------------------------------------------
    // Poll SurrealDB's TCP port until it is listening — no blind sleep.
    // This ensures Uvicorn's FastAPI startup handlers can initialize the
    // SurrealDB connection pool without hitting ECONNREFUSED.
    {
        let db_port = config.ports.database;
        let gate_timeout_secs = config.health.boot_timeout_secs.min(30);
        let probe_start = std::time::Instant::now();

        tracing::info!(
            db_port,
            gate_timeout_secs,
            "waiting for SurrealDB TCP port to become available before spawning Uvicorn"
        );

        let ready = tokio::time::timeout(
            std::time::Duration::from_secs(gate_timeout_secs),
            async {
                loop {
                    match tokio::net::TcpStream::connect(("127.0.0.1", db_port)).await {
                        Ok(_) => return true,
                        Err(_) => {
                            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                        }
                    }
                }
            },
        )
        .await;

        let elapsed_ms = probe_start.elapsed().as_millis();

        match ready {
            Ok(true) => {
                tracing::info!(
                    db_port,
                    elapsed_ms,
                    "SurrealDB TCP port is ready — proceeding with Uvicorn spawn"
                );
            }
            _ => {
                let reason = format!(
                    "SurrealDB TCP port {db_port} did not become available within \
                     {gate_timeout_secs}s (waited {elapsed_ms}ms) — cannot start Uvicorn"
                );
                tracing::error!(reason);
                state.write().transition(LauncherState::Failed { reason: reason.clone() });
                tray::refresh(&app, state.read().current())?;
                return Err(anyhow::anyhow!(reason));
            }
        }
    }

    // ------------------------------------------------------------------
    // Phase 2 — Spawn Python Uvicorn backend
    // ------------------------------------------------------------------
    tracing::info!(
        path = %config.aura_app_path.display(),
        port = %config.ports.backend,
        "spawning Python Uvicorn backend natively"
    );

    if let Err(e) = bridge.spawn_uvicorn(
        &config.aura_app_path.display().to_string(),
        config.ports.backend,
        true, // --reload for development
    ) {
        let reason = format!("failed to spawn Uvicorn backend: {e}");
        state.write().transition(LauncherState::Failed { reason: reason.clone() });
        tray::refresh(&app, state.read().current())?;
        return Err(anyhow::anyhow!(reason));
    }

    // Start streaming SurrealDB and Uvicorn logs to the host terminal.
    bridge.spawn_log_readers();

    // ------------------------------------------------------------------
    // Phase 2.5 — (Optional) SGLang Inference Server
    // ------------------------------------------------------------------
    if config.inference.enabled {
        tracing::info!(
            model_path = %config.inference.model_path,
            "spawning SGLang inference server natively"
        );

        if let Err(e) = bridge.spawn_sglang(
            &config.inference.model_path,
            30000,
        ) {
            let reason = format!("failed to spawn SGLang inference server: {e}");
            state.write().transition(LauncherState::Failed { reason: reason.clone() });
            tray::refresh(&app, state.read().current())?;
            return Err(anyhow::anyhow!(reason));
        }
    }

    // ------------------------------------------------------------------
    // Phase 3 — (Optional) Bare-metal Qwen3-TTS
    // ------------------------------------------------------------------
    if config.tts.enabled {
        if let Some(ref tts_path) = config.tts.tts_path {
            if let Err(e) = tts.start(
                &tts_path.display().to_string(),
                config.tts.port,
                &config.tts.model_dir,
                &config.tts.server_script,
            ) {
                let reason = format!("failed to start Qwen3-TTS: {e}");
                state.write().transition(LauncherState::Failed { reason });
                tray::refresh(&app, state.read().current())?;
                return Err(e);
            }
            // Stream TTS stdout/stderr to the frontend.
            tts.spawn_log_readers(&app);
        } else {
            let reason = "tts.enabled is true but tts_path is missing in aura.config.toml".into();
            state.write().transition(LauncherState::Failed { reason });
            tray::refresh(&app, state.read().current())?;
            return Err(anyhow::anyhow!("TTS enabled but path/env not configured"));
        }
    }

    // ------------------------------------------------------------------
    // Phase 4 — Health checks
    // ------------------------------------------------------------------
    state.write().transition(LauncherState::ServicesUp);
    tray::refresh(&app, state.read().current())?;

    state.write().transition(LauncherState::HealthChecking);
    tray::refresh(&app, state.read().current())?;

    let checker = HealthChecker::new(config.clone());
    if let Err(e) = checker.wait_until_healthy(config.health.boot_timeout_secs).await {
        let reason = format!("services did not become healthy: {e}");
        state.write().transition(LauncherState::Failed { reason });
        tray::refresh(&app, state.read().current())?;
        return Err(e);
    }

    // ------------------------------------------------------------------
    // Phase 5 — Ready
    // ------------------------------------------------------------------
    state.write().transition(LauncherState::Ready);
    tray::refresh(&app, state.read().current())?;

    // ------------------------------------------------------------------
    // Phase 5.5 — Liveness watchdog (state-correcting supervision loop)
    // ------------------------------------------------------------------
    // Polls process liveness every 5 seconds.  If a child process dies
    // without Tauri initiating the shutdown (e.g. crash, OOM kill), the
    // state machine will detect the desync and auto-transition to Failed.
    // This prevents the "ServicesUp while process is dead" state mismatch.
    {
        let bridge_watch = bridge.clone();
        let state_watch = state.clone();
        let tray_app = app.clone();
        tauri::async_runtime::spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;

                let surreal_alive = bridge_watch.is_surrealdb_alive();
                let uvicorn_alive = bridge_watch.is_uvicorn_alive();
                let sglang_alive = bridge_watch.is_sglang_alive();
                let current = state_watch.read().current().clone();

                // Only monitor while we think services should be running.
                let should_be_running = matches!(
                    current,
                    LauncherState::Ready
                        | LauncherState::ServicesUp
                        | LauncherState::HealthChecking
                );

                if !should_be_running {
                    // We're in Stopping/Stopped/Failed/Idle — watchdog can sleep.
                    continue;
                }

                if surreal_alive && uvicorn_alive && sglang_alive {
                    tracing::trace!(
                        surreal_alive,
                        uvicorn_alive,
                        sglang_alive,
                        "liveness watchdog: all processes healthy"
                    );
                } else {
                    let reason = format!(
                        "unexpected process death detected by liveness watchdog \
                         (SurrealDB={surreal_alive}, Uvicorn={uvicorn_alive}, SGLang={sglang_alive})"
                    );
                    tracing::error!(reason);
                    state_watch
                        .write()
                        .transition(LauncherState::Failed { reason: reason.clone() });
                    let _ = tray::refresh(&tray_app, state_watch.read().current());
                }
            }
        });
    }

    let _ = app
        .notification()
        .builder()
        .title("Aura")
        .body("Aura is awake. Click to open Mission Control.")
        .show();

    let _ = commands::open_mission_control_internal(&app);
    Ok(())
}

fn init_logging() {
    let log_dir = config::log_dir();
    let _ = std::fs::create_dir_all(&log_dir);
    let file_appender = tracing_appender::rolling::daily(&log_dir, "aura-launcher.log");
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,aura_launcher_lib=debug")),
        )
        .with_writer(file_appender)
        .with_ansi(false)
        .try_init();
}
