use std::sync::Arc;

use anyhow::{anyhow, Context};
use parking_lot::RwLock;
use serde::Serialize;
use tauri::{AppHandle, Manager, Runtime, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_opener::OpenerExt;
use tokio::process::Command;

use crate::config::{self, AuraConfig};
use crate::health::{HealthChecker, HealthSnapshot};
use crate::process_bridge::ProcessBridge;
use crate::state::{LauncherState, StateMachine};
use crate::tray;
use crate::tts_supervisor::TtsSupervisor;

pub type SharedState = Arc<RwLock<StateMachine>>;
pub type SharedTts = Arc<TtsSupervisor>;
pub type SharedBridge = Arc<ProcessBridge>;

#[derive(Debug, Serialize)]
pub struct StatusPayload {
    pub state: LauncherState,
    pub health: HealthSnapshot,
    pub config: PublicConfig,
}

#[derive(Debug, Serialize)]
pub struct PublicConfig {
    pub aura_app_path: String,
    pub mission_control_url: String,
    pub ide_url: String,
}

/// Pull a clone of the managed `AuraConfig` out of Tauri state.
/// Uses fully-qualified syntax so we never accidentally clone the *reference*
/// (Rust's blanket `&T: Clone` impl wins method dispatch on `(&Arc<…>).clone()`
/// and returns `&Arc<…>`, which then fails to outlive the dropped `State`
/// guard). FQS forces the deref-clone path.
fn config_of<R: Runtime>(app: &AppHandle<R>) -> AuraConfig {
    AuraConfig::clone(app.state::<AuraConfig>().inner())
}

fn state_of<R: Runtime>(app: &AppHandle<R>) -> SharedState {
    Arc::clone(app.state::<SharedState>().inner())
}

fn tts_of<R: Runtime>(app: &AppHandle<R>) -> SharedTts {
    Arc::clone(app.state::<SharedTts>().inner())
}

fn bridge_of<R: Runtime>(app: &AppHandle<R>) -> SharedBridge {
    Arc::clone(app.state::<SharedBridge>().inner())
}

// ===== Tauri commands (callable from WebView dialogs) =====

#[tauri::command]
pub async fn get_status<R: Runtime>(app: AppHandle<R>) -> Result<StatusPayload, String> {
    let config = config_of(&app);
    let state_arc = state_of(&app);
    let snapshot = HealthChecker::new(config.clone()).snapshot().await;
    let current_state: LauncherState = state_arc.read().current().clone();
    Ok(StatusPayload {
        state: current_state,
        health: snapshot,
        config: PublicConfig {
            aura_app_path: config.aura_app_path.display().to_string(),
            mission_control_url: config.mission_control_url(),
            ide_url: config.ide_url(),
        },
    })
}

#[tauri::command]
pub async fn start_aura<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    start_aura_internal(&app).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn stop_aura<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    stop_aura_internal(&app).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn restart_backend<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    restart_backend_internal(&app).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn open_url<R: Runtime>(app: AppHandle<R>, url: String) -> Result<(), String> {
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn save_env<R: Runtime>(app: AppHandle<R>, contents: String) -> Result<(), String> {
    let config = config_of(&app);
    let path = config.env_file_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    std::fs::write(&path, contents).map_err(|e| format!("write {}: {e}", path.display()))?;
    tracing::info!(path = %path.display(), "wrote .env");
    Ok(())
}

// ===== Internal helpers reused by tray =====

pub fn open_mission_control_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let config = config_of(app);
    app.opener().open_url(config.mission_control_url(), None::<&str>)?;
    Ok(())
}

pub fn open_ide_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let config = config_of(app);
    app.opener().open_url(config.ide_url(), None::<&str>)?;
    Ok(())
}

pub fn open_logs_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let dir = config::log_dir();
    std::fs::create_dir_all(&dir).ok();
    app.opener().open_path(dir.display().to_string(), None::<&str>)?;
    Ok(())
}

pub async fn start_aura_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let config = config_of(app);
    let state = state_of(app);
    let tts = tts_of(app);
    let bridge = bridge_of(app);
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = crate::boot_pipeline(app_handle, state, config, tts, bridge).await {
            tracing::error!(error = %e, "manual start failed");
        }
    });
    Ok(())
}

/// Stop Aura by gracefully shutting down all native child processes
/// (SurrealDB + Uvicorn + TTS) with HTTP IPC, falling back to force-kill
/// only after a configurable timeout.
pub async fn stop_aura_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let config = config_of(app);
    let state = state_of(app);
    let bridge = bridge_of(app);
    let tts = tts_of(app);

    state.write().transition(LauncherState::Stopping);
    tray::refresh(app, state.read().current())?;

    // 1. Kill the bare-metal TTS process if it is running.
    if let Err(e) = tts.stop() {
        tracing::warn!(error = %e, "failed to stop TTS during shutdown");
    }

    // 2. Graceful HTTP IPC shutdown -> force-kill fallback after 3000ms.
    bridge
        .shutdown_gracefully(
            &config.surrealdb.user,
            &config.surrealdb.pass,
            config.ports.database,
            3000, // fall back to force-kill after 3 s
        )
        .await;

    state.write().transition(LauncherState::Stopped);
    tray::refresh(app, state.read().current())?;
    tracing::info!("all native backend services stopped");
    Ok(())
}

/// Restart only the Python Uvicorn backend.
///
/// Kills the existing Uvicorn child process and spawns a fresh one.
pub async fn restart_backend_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let config = config_of(app);
    let bridge = bridge_of(app);

    tracing::info!("restarting Python Uvicorn backend");

    // Kill existing Uvicorn process.
    bridge.kill_all(); // kill_all is safe — it only touches tracked children

    // Give the port a moment to be released.
    tokio::time::sleep(std::time::Duration::from_secs(1)).await;

    // Spawn a fresh Uvicorn instance.
    bridge.spawn_uvicorn(
        &config.aura_app_path.display().to_string(),
        config.ports.backend,
        true,
    )?;

    tracing::info!("Uvicorn backend restarted");
    Ok(())
}

pub async fn restart_all_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    stop_aura_internal(app).await?;
    start_aura_internal(app).await?;
    Ok(())
}

/// Sync & Rebuild Core — pulls latest git changes and restarts services.
///
/// In sovereign-native mode this does a `git pull` followed by a full
/// restart (kill + respawn) of all backend services.
pub async fn sync_and_rebuild_core_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let config = config_of(app);
    let state = state_of(app);

    state.write().transition(LauncherState::ServicesStarting);
    tray::refresh(app, state.read().current())?;

    run_logged_command(
        "git pull origin main",
        Command::new("git")
            .args(["pull", "origin", "main"])
            .current_dir(&config.aura_app_path),
    )
    .await?;

    notify(app, "Pull successful. Restarting Aura services...");

    // Full restart: graceful shutdown, then re-spawn.
    stop_aura_internal(app).await?;
    start_aura_internal(app).await?;

    state.write().transition(LauncherState::Ready);
    tray::refresh(app, state.read().current())?;
    notify(app, "Aura Core updated and running.");
    Ok(())
}

async fn run_logged_command(label: &str, command: &mut Command) -> anyhow::Result<()> {
    tracing::info!(command = label, "starting native update pipeline command");
    apply_no_window(command);
    let output = command
        .output()
        .await
        .with_context(|| format!("failed to execute {label}"))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    if !stdout.trim().is_empty() {
        tracing::info!(command = label, stdout = %stdout, "command stdout");
    }
    if !stderr.trim().is_empty() {
        tracing::warn!(command = label, stderr = %stderr, "command stderr");
    }

    if output.status.success() {
        tracing::info!(command = label, status = %output.status, "command completed successfully");
        Ok(())
    } else {
        Err(anyhow!("{label} failed with status {}", output.status))
    }
}

fn notify<R: Runtime>(app: &AppHandle<R>, body: &str) {
    let _ = app.notification().builder().title("Aura").body(body).show();
}

pub fn open_env_editor_internal<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    if let Some(window) = app.get_webview_window("env-editor") {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }

    WebviewWindowBuilder::new(app, "env-editor", WebviewUrl::App("env-editor.html".into()))
        .title("Aura — Edit .env")
        .inner_size(560.0, 420.0)
        .resizable(false)
        .always_on_top(true)
        .center()
        .build()?;
    Ok(())
}

/// Graceful shutdown: stop TTS, gracefully shut down SurrealDB + Uvicorn
/// via HTTP IPC with force-kill fallback, then exit.
///
/// This is async so that cleanup can complete. The function calls
/// `std::process::exit(0)` at the end and never returns.
pub async fn quit_launcher_internal<R: Runtime>(app: &AppHandle<R>) {
    tracing::info!("quit launcher requested — running sovereign-native graceful shutdown sequence");

    let config = config_of(app);

    // 1. Kill the bare-metal TTS process if it is running.
    let tts = tts_of(app);
    if let Err(e) = tts.stop() {
        tracing::warn!(error = %e, "failed to stop TTS during quit");
    }

    // 2. Graceful HTTP IPC shutdown for SurrealDB + Uvicorn.
    let bridge = bridge_of(app);
    let state = state_of(app);

    state.write().transition(LauncherState::Stopping);
    let _ = tray::refresh(app, state.read().current());

    bridge
        .shutdown_gracefully(
            &config.surrealdb.user,
            &config.surrealdb.pass,
            config.ports.database,
            3000, // fall back to force-kill after 3 s
        )
        .await;

    state.write().transition(LauncherState::Stopped);
    let _ = tray::refresh(app, state.read().current());
    tracing::info!("all native backend services gracefully shut down — exiting");

    app.cleanup_before_exit();
    std::process::exit(0);
}

// ---------------------------------------------------------------------------
// Windows: hide console window for non-visible commands (git, etc.)
// ---------------------------------------------------------------------------

#[cfg(windows)]
fn apply_no_window(cmd: &mut Command) {
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn apply_no_window(_cmd: &mut Command) {}
