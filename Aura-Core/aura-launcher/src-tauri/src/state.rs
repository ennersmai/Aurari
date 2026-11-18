use std::time::Instant;

use serde::Serialize;

/// Sovereign-native state machine for the Aura Launcher.
///
/// Replaces the old Docker-centric states (`DockerStarting`, `ComposeUp`)
/// with bare-metal equivalents (`ServicesStarting`, `ServicesUp`).
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LauncherState {
    Idle,
    /// Tauri is spawning SurrealDB + Uvicorn as native OS child processes.
    ServicesStarting,
    /// Both backend services have been spawned; waiting for health checks.
    ServicesUp,
    /// Polling `/health` endpoints until they return 200.
    HealthChecking,
    /// All services are healthy and Aura is ready.
    Ready,
    /// Shutdown sequence in progress (killing child processes).
    Stopping,
    /// All services have been stopped.
    Stopped,
    /// Terminal failure with a human-readable reason.
    Failed { reason: String },
}

impl LauncherState {
    pub fn label(&self) -> String {
        match self {
            Self::Idle => "Initializing…".into(),
            Self::ServicesStarting => "Starting backend services…".into(),
            Self::ServicesUp => "Services spawned — waiting for health…".into(),
            Self::HealthChecking => "Waiting for services to be healthy…".into(),
            Self::Ready => "Aura is awake".into(),
            Self::Stopping => "Stopping Aura…".into(),
            Self::Stopped => "Aura is stopped".into(),
            Self::Failed { reason } => format!("Launcher failed: {reason}"),
        }
    }

    pub fn icon_variant(&self) -> IconVariant {
        match self {
            Self::Idle | Self::Stopped => IconVariant::Stopped,
            Self::ServicesStarting | Self::ServicesUp | Self::HealthChecking | Self::Stopping => {
                IconVariant::Starting
            }
            Self::Ready => IconVariant::Ready,
            Self::Failed { .. } => IconVariant::Failed,
        }
    }

    pub fn is_terminal_failure(&self) -> bool {
        matches!(self, Self::Failed { .. })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IconVariant {
    Stopped,
    Starting,
    Ready,
    Failed,
}

#[derive(Debug)]
pub struct StateMachine {
    state: LauncherState,
    last_transition: Instant,
}

impl StateMachine {
    pub fn new() -> Self {
        Self { state: LauncherState::Idle, last_transition: Instant::now() }
    }

    pub fn transition(&mut self, next: LauncherState) {
        tracing::info!(from = ?self.state, to = ?next, "state transition");
        self.state = next;
        self.last_transition = Instant::now();
    }

    pub fn current(&self) -> &LauncherState {
        &self.state
    }

    pub fn elapsed(&self) -> std::time::Duration {
        self.last_transition.elapsed()
    }
}

impl Default for StateMachine {
    fn default() -> Self {
        Self::new()
    }
}
