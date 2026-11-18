//! Sovereign Native Process Bridge — bare-metal child-process orchestrator.
//!
//! Spawns SurrealDB and the Python AI Engine (Uvicorn) as headless OS-level
//! child processes.  Stdout and stderr are captured via Rust pipes and
//! multiplexed directly into the **host launch console** with visual
//! `[SurrealDB]` / `[Uvicorn]` tags.
//!
//! # Design
//!
//! * Each backend service spawns directly (no `cmd.exe` wrapper) with
//!   `CREATE_NO_WINDOW` so nothing flashes on screen.
//! * Log streaming runs in dedicated background threads per service,
//!   writing to `println!` (stdout) and `eprintln!` (stderr).
//! * On shutdown we first attempt graceful HTTP IPC termination, then
//!   fall back to `TerminateProcess` only after a configurable timeout.
//! * The real process PIDs are tracked — no shell-indirection orphans.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command as StdCommand, Stdio};
use std::thread;
use std::time::Duration;

use anyhow::{Context, Result};
use parking_lot::Mutex;

// ---------------------------------------------------------------------------
// Windows: CREATE_NO_WINDOW so processes run headless (no flashing cmd.exe).
// ---------------------------------------------------------------------------
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Holds the OS child-process handles for SurrealDB and the Python Uvicorn
/// backend.  Wrapped in `Arc<Mutex<>>` so it can be shared with the Tauri
/// shutdown hook.
pub struct ProcessBridge {
    /// SurrealDB child process (headless).
    surrealdb: Mutex<Option<Child>>,
    /// Python Uvicorn child process (headless).
    uvicorn: Mutex<Option<Child>>,
    /// SGLang inference server child process (headless).
    sglang: Mutex<Option<Child>>,
    /// Backend HTTP port, stored for graceful-shutdown requests.
    backend_port: Mutex<u16>,
}

impl ProcessBridge {
    /// Create a new, empty process bridge.
    pub fn new() -> Self {
        Self {
            surrealdb: Mutex::new(None),
            uvicorn: Mutex::new(None),
            sglang: Mutex::new(None),
            backend_port: Mutex::new(8080),
        }
    }

    // ------------------------------------------------------------------
    // Service A — SurrealDB
    // ------------------------------------------------------------------

    /// Spawn SurrealDB as a **headless** process.
    ///
    /// No `cmd.exe` wrapper — we spawn `surreal` directly so the tracked PID
    /// is the real database process.  Stdout and stderr are piped; call
    /// [`spawn_log_readers`] afterwards to stream them to the frontend.
    ///
    /// # Arguments
    /// * `user` - SurrealDB root user (default: `"root"`).
    /// * `pass` - SurrealDB root password (default: `"root"`).
    /// * `port` - TCP port to bind (default: `8000`).
    pub fn spawn_surrealdb(
        &self,
        user: &str,
        pass: &str,
        port: u16,
    ) -> Result<()> {
        let bind = format!("127.0.0.1:{port}");

        tracing::info!(
            %user, %port,
            "spawning SurrealDB headless (no console window)"
        );

        let mut cmd = StdCommand::new("surreal");
        cmd.args([
            "start",
            "--log", "trace",
            "--user", user,
            "--pass", pass,
            "--bind", &bind,
            "memory",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

        // Hide the console window on Windows.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let child = cmd
            .spawn()
            .context("failed to spawn SurrealDB (is `surreal` on PATH?)")?;

        let pid = child.id();
        tracing::info!(pid, "SurrealDB spawned headless");

        *self.surrealdb.lock() = Some(child);
        Ok(())
    }

    // ------------------------------------------------------------------
    // Service B — Python AI Engine (Uvicorn / FastAPI)
    // ------------------------------------------------------------------

    /// Spawn the Python Uvicorn backend as a **headless** process.
    ///
    /// The working directory is set to `aura_app_path` so that relative
    /// imports and `.env` resolution work correctly.
    ///
    /// # Arguments
    /// * `aura_app_path` - Absolute path to the `aura-app/` directory
    ///   (contains `src/aura/main.py` and `.env`).
    /// * `port` - TCP port for the FastAPI server (default: `8080`).
    /// * `reload` - Enable `--reload` for development hot-reload.
    pub fn spawn_uvicorn(
        &self,
        aura_app_path: &str,
        port: u16,
        reload: bool,
    ) -> Result<()> {
        // Resolve the absolute path so current_dir is reliable.
        let canonical = dunce::canonicalize(aura_app_path)
            .unwrap_or_else(|_| PathBuf::from(aura_app_path));

        let mut args = vec![
            "-m".to_string(),
            "uvicorn".to_string(),
            "aura.main:app".to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            port.to_string(),
        ];
        if reload {
            args.push("--reload".to_string());
        }

        tracing::info!(
            path = %canonical.display(),
            %port,
            reload,
            "spawning Python Uvicorn backend headless (no console window)"
        );

        let mut cmd = StdCommand::new("python");
        cmd.args(&args)
            .current_dir(&canonical)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Hide the console window on Windows.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let child = cmd
            .spawn()
            .context("failed to spawn Uvicorn backend (is `python` available with `uvicorn` installed?)")?;

        let pid = child.id();
        tracing::info!(pid, "Uvicorn spawned headless");

        *self.backend_port.lock() = port;
        *self.uvicorn.lock() = Some(child);
        Ok(())
    }

    // ------------------------------------------------------------------
    // Service C — SGLang Inference Server (OpenAI-compatible)
    // ------------------------------------------------------------------

    /// Spawn the SGLang inference server as a **headless** process.
    ///
    /// Launches `python -m sglang.launch_server` with the configured model
    /// path, binding to localhost on the given port with `--api-key sk-local`.
    ///
    /// # Arguments
    /// * `model_path` - Path to the model directory (e.g. `"./models/gemma2-27b"`).
    /// * `port` - TCP port for the OpenAI-compatible API (default: `30000`).
    pub fn spawn_sglang(
        &self,
        model_path: &str,
        port: u16,
    ) -> Result<()> {
        tracing::info!(
            %model_path,
            %port,
            "spawning SGLang inference server headless (no console window)"
        );

        let mut cmd = StdCommand::new("python");
        cmd.args([
            "-m", "sglang.launch_server",
            "--model-path", model_path,
            "--port", &port.to_string(),
            "--host", "127.0.0.1",
            "--api-key", "sk-local",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

        // Hide the console window on Windows.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let child = cmd
            .spawn()
            .context("failed to spawn SGLang inference server (is `python` available with `sglang` installed?)")?;

        let pid = child.id();
        tracing::info!(pid, "SGLang spawned headless");

        *self.sglang.lock() = Some(child);
        Ok(())
    }

    // ------------------------------------------------------------------
    // Log streaming
    // ------------------------------------------------------------------

    /// Spawn background threads that read SurrealDB's, Uvicorn's, and
    /// SGLang's stdout/stderr and multiplex them directly into the **host
    /// launch console** via `println!` (stdout) and `eprintln!` (stderr).
    ///
    /// Call this immediately after all services have been spawned (or at
    /// least after each individual spawn).  Idempotent — calling multiple
    /// times will start duplicate readers if the previous pipes haven't
    /// been taken; in practice this is harmless because `Child::stdout.take()`
    /// returns `None` after the first call.
    pub fn spawn_log_readers(&self) {
        spawn_console_reader("SurrealDB", "surrealdb", &self.surrealdb);
        spawn_console_reader("Uvicorn", "uvicorn", &self.uvicorn);
        spawn_console_reader("SGLang", "sglang", &self.sglang);
    }
}

// ---------------------------------------------------------------------------
// Console log reader (free function — no Tauri dependency)
// ---------------------------------------------------------------------------

/// Spawn background threads that read a child process's stdout/stderr and
/// write each line to the host terminal with a visual `[label]` tag.
///
/// * `label` — human-readable display tag (e.g. `"SurrealDB"`).
/// * `source` — tracing span name (e.g. `"surrealdb"`).
fn spawn_console_reader(label: &'static str, source: &'static str, lock: &Mutex<Option<Child>>) {
    let mut guard = lock.lock();
    let Some(ref mut child) = *guard else {
        tracing::debug!(%source, "spawn_console_reader: no child process to read from");
        return;
    };

    // Take stdout/stderr out of the child (they're consumed by the threads).
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    // --- stdout reader thread ---
    if let Some(stdout) = stdout {
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                match line {
                    Ok(text) => {
                        println!("[{label}] {text}");
                    }
                    Err(e) => {
                        eprintln!("[{label}] [ERROR reading stdout: {e}]");
                        break;
                    }
                }
            }
            tracing::info!(%source, "stdout reader finished");
        });
    }

    // --- stderr reader thread ---
    if let Some(stderr) = stderr {
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                match line {
                    Ok(text) => {
                        eprintln!("[{label}] {text}");
                    }
                    Err(e) => {
                        eprintln!("[{label}] [ERROR reading stderr: {e}]");
                        break;
                    }
                }
            }
            tracing::info!(%source, "stderr reader finished");
        });
    }
}

// ---------------------------------------------------------------------------
// Health checks & lifecycle (impl ProcessBridge continued)
// ---------------------------------------------------------------------------

impl ProcessBridge {
    /// Returns `true` if the SurrealDB child process is still running.
    pub fn is_surrealdb_alive(&self) -> bool {
        check_child_alive(&self.surrealdb)
    }

    /// Returns `true` if the Uvicorn child process is still running.
    pub fn is_uvicorn_alive(&self) -> bool {
        check_child_alive(&self.uvicorn)
    }

    /// Returns `true` if the SGLang child process is still running, or if
    /// SGLang was never spawned (i.e. `inference.enabled = false`).
    ///
    /// When SGLang is not configured, this always returns `true` so that
    /// the liveness watchdog and graceful-shutdown loops don't treat a
    /// missing optional service as a failure.
    pub fn is_sglang_alive(&self) -> bool {
        let guard = self.sglang.lock();
        if guard.is_none() {
            return true; // not enabled — nothing to monitor
        }
        drop(guard);
        check_child_alive(&self.sglang)
    }

    // ------------------------------------------------------------------
    // Graceful HTTP IPC shutdown (Fix C)
    // ------------------------------------------------------------------

    /// Attempt graceful shutdown of Uvicorn via HTTP POST.
    ///
    /// Sends `POST http://127.0.0.1:{port}/v1/system/shutdown` with a short
    /// timeout.  Returns `Ok(true)` if the server acknowledged the shutdown,
    /// `Ok(false)` if the endpoint returned a non-success status (e.g. 404
    /// if the endpoint hasn't been implemented yet), and `Err` on connection
    /// failure (server already dead).
    pub async fn shutdown_uvicorn_http(&self) -> Result<bool> {
        let port = *self.backend_port.lock();
        let url = format!("http://127.0.0.1:{port}/v1/system/shutdown");
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
            .context("failed to build reqwest client for uvicorn shutdown")?;

        tracing::info!(%url, "sending graceful HTTP shutdown to Uvicorn");

        match client.post(&url).send().await {
            Ok(r) if r.status().is_success() => {
                tracing::info!(
                    status = %r.status(),
                    "Uvicorn acknowledged graceful shutdown"
                );
                Ok(true)
            }
            Ok(r) => {
                tracing::warn!(
                    status = %r.status(),
                    "Uvicorn shutdown endpoint returned non-success \
                     (endpoint may not exist — falling back to force kill)"
                );
                Ok(false)
            }
            Err(e) => {
                tracing::warn!(
                    error = %e,
                    "Uvicorn shutdown HTTP request failed (server may already be down)"
                );
                Err(anyhow::anyhow!("uvicorn shutdown HTTP request failed: {e}"))
            }
        }
    }

    /// Attempt graceful shutdown of SurrealDB via its HTTP RPC API.
    ///
    /// SurrealDB doesn't expose a dedicated shutdown endpoint, but we can
    /// issue a `SHUTDOWN` statement through its SQL endpoint.
    /// Returns `Ok(true)` if the command was accepted.
    pub async fn shutdown_surrealdb_http(
        &self,
        user: &str,
        pass: &str,
        port: u16,
    ) -> Result<bool> {
        let url = format!("http://127.0.0.1:{port}/sql");
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
            .context("failed to build reqwest client for surrealdb shutdown")?;

        tracing::info!(%url, "sending graceful shutdown to SurrealDB via SHUTDOWN SQL");

        // SurrealDB SHUTDOWN command via its SQL endpoint.
        // If the version doesn't support SHUTDOWN, this returns an error
        // and we fall back to force kill — safe for in-memory mode.
        match client
            .post(&url)
            .basic_auth(user, Some(pass))
            .header("NS", "aura")
            .header("DB", "aura")
            .header("Accept", "application/json")
            .body("SHUTDOWN")
            .send()
            .await
        {
            Ok(r) if r.status().is_success() => {
                tracing::info!("SurrealDB accepted SHUTDOWN command");
                Ok(true)
            }
            Ok(r) => {
                tracing::warn!(
                    status = %r.status(),
                    "SurrealDB SHUTDOWN returned non-success \
                     (command may not be supported — falling back to force kill)"
                );
                Ok(false)
            }
            Err(e) => {
                tracing::warn!(
                    error = %e,
                    "SurrealDB shutdown HTTP request failed (server may already be down)"
                );
                Err(anyhow::anyhow!("surrealdb shutdown HTTP request failed: {e}"))
            }
        }
    }

    /// Graceful shutdown sequence for all tracked processes.
    ///
    /// 1. Send HTTP termination requests to Uvicorn and SurrealDB.
    /// 2. Wait up to `grace_timeout_ms` for processes to exit on their own.
    /// 3. Fall back to `kill_all()` for any process still alive.
    pub async fn shutdown_gracefully(
        &self,
        surreal_user: &str,
        surreal_pass: &str,
        surreal_port: u16,
        grace_timeout_ms: u64,
    ) {
        tracing::info!(
            grace_timeout_ms,
            "beginning graceful shutdown sequence"
        );

        // Phase 1 — send HTTP termination requests (best-effort).
        let _ = self.shutdown_uvicorn_http().await;
        let _ = self.shutdown_surrealdb_http(surreal_user, surreal_pass, surreal_port).await;

        // Phase 2 — wait for processes to exit on their own.
        let deadline = std::time::Instant::now() + Duration::from_millis(grace_timeout_ms);
        loop {
            let surreal_alive = self.is_surrealdb_alive();
            let uvicorn_alive = self.is_uvicorn_alive();
            let sglang_alive = self.is_sglang_alive();

            if !surreal_alive && !uvicorn_alive && !sglang_alive {
                tracing::info!("all processes exited cleanly after graceful shutdown");
                return;
            }

            if std::time::Instant::now() >= deadline {
                tracing::warn!(
                    surreal_alive,
                    uvicorn_alive,
                    sglang_alive,
                    "graceful shutdown timeout reached — falling back to force kill"
                );
                break;
            }

            tokio::time::sleep(Duration::from_millis(200)).await;
        }

        // Phase 3 — force kill any remaining processes.
        self.kill_all();
    }

    // ------------------------------------------------------------------
    // Force-kill teardown (last-resort fallback)
    // ------------------------------------------------------------------

    /// Force-kill **all** spawned backend processes via `TerminateProcess`.
    ///
    /// This is the last-resort fallback after [`shutdown_gracefully`] has
    /// timed out.  On Windows, `child.kill()` calls `TerminateProcess()`
    /// which is equivalent to SIGKILL — no flush, no cleanup.
    ///
    /// For the current in-memory SurrealDB deployment this is safe; a future
    /// switch to file-backed storage should ensure [`shutdown_gracefully`]
    /// is always called first.
    pub fn kill_all(&self) {
        force_kill_child("SurrealDB", &self.surrealdb);
        force_kill_child("Uvicorn", &self.uvicorn);
        force_kill_child("SGLang", &self.sglang);
    }
}

impl Default for ProcessBridge {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Check whether a child process stored behind a `Mutex<Option<Child>>`
/// is still running.  If the process has exited, the handle is cleared
/// from the slot so subsequent checks return `false` immediately.
fn check_child_alive(lock: &Mutex<Option<Child>>) -> bool {
    let mut guard = lock.lock();
    if let Some(ref mut child) = *guard {
        match child.try_wait() {
            Ok(None) => true, // still running
            Ok(Some(status)) => {
                tracing::warn!(
                    pid = child.id(),
                    ?status,
                    "child process exited unexpectedly"
                );
                *guard = None;
                false
            }
            Err(e) => {
                tracing::error!(
                    pid = child.id(),
                    error = %e,
                    "failed to check child process status"
                );
                false
            }
        }
    } else {
        false
    }
}

/// Force-kill a single child process with `TerminateProcess` (Windows) or
/// `SIGKILL` (Unix).  No graceful shutdown — use [`ProcessBridge::shutdown_gracefully`]
/// for that.
fn force_kill_child(label: &str, lock: &Mutex<Option<Child>>) {
    let mut guard = lock.lock();
    let Some(mut child) = guard.take() else {
        return;
    };

    let pid = child.id();
    tracing::info!(%label, pid, "force-killing child process (TerminateProcess / SIGKILL)");

    if let Err(e) = child.kill() {
        tracing::warn!(%label, pid, error = %e, "force kill failed, will try taskkill");
    }

    // Give the OS a moment to reap the process.
    std::thread::sleep(Duration::from_millis(500));

    match child.try_wait() {
        Ok(Some(status)) => {
            tracing::info!(%label, pid, ?status, "child process exited after kill");
        }
        Ok(None) => {
            tracing::warn!(%label, pid, "child still alive after kill — invoking taskkill /F");
            force_kill_windows_tree(pid);
            let _ = child.wait();
        }
        Err(e) => {
            tracing::error!(%label, pid, error = %e, "failed to check child status after kill");
            force_kill_windows_tree(pid);
        }
    }

    tracing::info!(%label, pid, "child process stopped");
}

/// Last-resort kill via `taskkill /F /PID <pid> /T` (tree kill).
///
/// `/T` ensures any orphaned grandchildren are also terminated.
#[cfg(windows)]
fn force_kill_windows_tree(pid: u32) {
    let result = StdCommand::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    match result {
        Ok(status) if status.success() => {
            tracing::info!(pid, "taskkill /F /T succeeded");
        }
        Ok(status) => {
            tracing::warn!(pid, exit_code = ?status.code(), "taskkill /F /T returned non-zero");
        }
        Err(e) => {
            tracing::error!(pid, error = %e, "failed to invoke taskkill");
        }
    }
}

#[cfg(not(windows))]
fn force_kill_windows_tree(pid: u32) {
    tracing::warn!(pid, "force_kill_windows_tree called on non-Windows platform — no-op");
}
