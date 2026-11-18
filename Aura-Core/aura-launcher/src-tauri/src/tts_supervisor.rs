//! Bare-metal Qwen3-TTS supervisor.
//!
//! Launches the Python Qwen3-TTS server via a standard Python virtual
//! environment (`venv`), tracks the child process, streams its stdout/stderr
//! to the frontend via Tauri events and SSE, and kills it on launcher shutdown.
//!
//! No conda. No CosyVoice. Just a lean venv with the pre-compiled Qwen3-TTS
//! wheel installed.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command as StdCommand, Stdio};
use std::thread;

use anyhow::{Context, Result};
use parking_lot::Mutex;
use serde::Serialize;
use tauri::Emitter;

/// Payload emitted as `system-log` event to the frontend.
#[derive(Debug, Clone, Serialize)]
pub struct SystemLogPayload {
    pub source: String,
    pub stream: String,
    pub line: String,
    pub timestamp: u64,
}

impl SystemLogPayload {
    pub fn now(source: &str, stream: &str, line: String) -> Self {
        Self {
            source: source.to_string(),
            stream: stream.to_string(),
            line,
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
        }
    }
}

/// Manages the lifecycle of a bare-metal Qwen3-TTS process.
///
/// The TTS server is expected to live in a standard Python `venv` at
/// `<tts_path>/venv/`.  The launcher invokes `<tts_path>/venv/Scripts/python.exe`
/// directly — no conda, no global environment searches.
pub struct TtsSupervisor {
    child: Mutex<Option<Child>>,
}

impl TtsSupervisor {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    /// Resolve the venv Python interpreter inside the TTS directory.
    ///
    /// Returns `Some(path)` if `<tts_path>/venv/Scripts/python.exe` exists,
    /// `None` otherwise.
    pub fn resolve_venv_python(tts_path: &str) -> Option<PathBuf> {
        let candidate = PathBuf::from(tts_path)
            .join("venv")
            .join("Scripts")
            .join("python.exe");
        if candidate.exists() {
            Some(candidate)
        } else {
            None
        }
    }

    /// Check whether a usable venv exists inside the given TTS path.
    pub fn is_venv_ready(tts_path: &str) -> bool {
        Self::resolve_venv_python(tts_path).is_some()
    }

    /// Launch the Qwen3-TTS FastAPI server using the venv's Python interpreter.
    ///
    /// Stdout and stderr are piped so the caller can stream them to the
    /// frontend via [`spawn_log_readers`].
    ///
    /// # Arguments
    /// * `tts_path` - Absolute path to the TTS directory (contains `venv/` and `server.py`).
    /// * `port` - TCP port for the TTS server.
    /// * `model_dir` - Path passed as `--model_dir` to `server.py`.
    /// * `server_script` - Relative path to the server script inside `tts_path`.
    pub fn start(
        &self,
        tts_path: &str,
        port: u16,
        model_dir: &str,
        server_script: &str,
    ) -> Result<()> {
        let python_exe = Self::resolve_venv_python(tts_path)
            .ok_or_else(|| anyhow::anyhow!(
                "venv not found at {}\\venv\\Scripts\\python.exe — run setup-env.ps1 first",
                tts_path
            ))?;

        let server_script_path = format!(
            "{}/{}",
            tts_path.trim_end_matches(['/', '\\']),
            server_script.trim_start_matches(['/', '\\']),
        );

        tracing::info!(
            tts_path = %tts_path,
            python = %python_exe.display(),
            port = %port,
            model_dir = %model_dir,
            script = %server_script_path,
            "launching Qwen3-TTS via venv Python"
        );

        let mut cmd = StdCommand::new(&python_exe);
        cmd.args([
            &server_script_path,
            "--port",
            &port.to_string(),
            "--model_dir",
            model_dir,
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

        // Hide the console window on Windows (TTS runs headless).
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let child = cmd
            .spawn()
            .with_context(|| format!("failed to spawn Qwen3-TTS (venv Python at {})", python_exe.display()))?;

        let pid = child.id();
        tracing::info!(pid, "Qwen3-TTS process started");

        *self.child.lock() = Some(child);
        Ok(())
    }

    /// Spawn background threads that read the Qwen3-TTS process's stdout/stderr
    /// and emit every line as a `system-log` event + SSE broadcast.
    ///
    /// Call this immediately after [`start`].
    pub fn spawn_log_readers<R: tauri::Runtime>(&self, app_handle: &tauri::AppHandle<R>) {
        let mut guard = self.child.lock();
        let Some(ref mut child) = *guard else {
            tracing::warn!("spawn_log_readers called but no child process exists");
            return;
        };

        // Take stdout/stderr out of the child (they're consumed by the threads).
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();

        // --- stdout reader thread ---
        if let Some(stdout) = stdout {
            let handle = app_handle.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines() {
                    match line {
                        Ok(text) => {
                            let payload = SystemLogPayload::now("qwen3-tts", "stdout", text);
                            let _ = handle.emit("system-log", payload.clone());
                            crate::log_server::broadcast(&payload);
                        }
                        Err(e) => {
                            tracing::error!(error = %e, "error reading qwen3-tts stdout");
                            break;
                        }
                    }
                }
                tracing::info!("qwen3-tts stdout reader finished");
            });
        }

        // --- stderr reader thread ---
        if let Some(stderr) = stderr {
            let handle = app_handle.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    match line {
                        Ok(text) => {
                            let payload = SystemLogPayload::now("qwen3-tts", "stderr", text);
                            let _ = handle.emit("system-log", payload.clone());
                            crate::log_server::broadcast(&payload);
                        }
                        Err(e) => {
                            tracing::error!(error = %e, "error reading qwen3-tts stderr");
                            break;
                        }
                    }
                }
                tracing::info!("qwen3-tts stderr reader finished");
            });
        }
    }

    /// Kill the TTS process if it is running.
    pub fn stop(&self) -> Result<()> {
        let mut guard = self.child.lock();
        if let Some(mut child) = guard.take() {
            let pid = child.id();
            tracing::info!(pid = pid, "stopping Qwen3-TTS");

            if let Err(e) = child.kill() {
                tracing::warn!(pid = pid, error = %e, "failed to kill TTS process");
            }
            if let Err(e) = child.wait() {
                tracing::warn!(pid = pid, error = %e, "failed to wait on TTS process");
            }

            tracing::info!(pid = pid, "Qwen3-TTS stopped");
        }
        Ok(())
    }

    /// Check whether the child process is still alive.
    pub fn is_running(&self) -> bool {
        let mut guard = self.child.lock();
        if let Some(ref mut child) = *guard {
            match child.try_wait() {
                Ok(None) => true,
                Ok(Some(status)) => {
                    tracing::warn!(pid = child.id(), ?status, "Qwen3-TTS exited unexpectedly");
                    *guard = None;
                    false
                }
                Err(e) => {
                    tracing::error!(pid = child.id(), error = %e, "failed to check Qwen3-TTS status");
                    false
                }
            }
        } else {
            false
        }
    }
}

impl Default for TtsSupervisor {
    fn default() -> Self {
        Self::new()
    }
}
