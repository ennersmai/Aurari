use std::time::Duration;

use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::Serialize;
use tokio::time::{sleep, Instant};

use crate::config::AuraConfig;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct HealthSnapshot {
    pub backend: bool,
    pub frontend: bool,
    pub database: bool,
    pub tts: bool,
}

impl HealthSnapshot {
    pub fn all_up(&self) -> bool {
        self.backend && self.frontend && self.database && self.tts
    }
}

pub struct HealthChecker {
    config: AuraConfig,
    client: Client,
}

impl HealthChecker {
    pub fn new(config: AuraConfig) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.health.probe_timeout_secs))
            .build()
            .expect("reqwest client must build");
        Self { config, client }
    }

    pub async fn snapshot(&self) -> HealthSnapshot {
        let backend_url = self.config.backend_health_url();
        let frontend_url = self.config.frontend_url();
        let db_port = self.config.ports.database;
        let tts_port = self.config.tts.port;

        let tts_enabled = self.config.tts.enabled;

        let (backend, frontend, database, tts) = tokio::join!(
            self.probe_http(&backend_url),
            self.probe_http(&frontend_url),
            self.probe_tcp(db_port),
            self.probe_tts(tts_port, tts_enabled),
        );
        HealthSnapshot { backend, frontend, database, tts }
    }

    /// Probe the TTS server. Uses HTTP GET to `/openapi.json` (FastAPI always
    /// serves this once the app is fully initialized with model in VRAM).
    /// A bare TCP connect can succeed before the model is loaded, causing
    /// 504s on the first `/voice/stream` request.
    ///
    /// If TTS is disabled, always reports healthy.
    async fn probe_tts(&self, port: u16, enabled: bool) -> bool {
        if !enabled {
            return true;
        }
        let url = format!("http://localhost:{port}/openapi.json");
        self.probe_http(&url).await
    }

    async fn probe_http(&self, url: &str) -> bool {
        match self.client.get(url).send().await {
            Ok(r) => r.status().is_success(),
            Err(e) => {
                tracing::trace!(url, error = %e, "http probe failed");
                false
            }
        }
    }

    async fn probe_tcp(&self, port: u16) -> bool {
        matches!(
            tokio::time::timeout(
                Duration::from_secs(self.config.health.probe_timeout_secs),
                tokio::net::TcpStream::connect(("127.0.0.1", port)),
            )
            .await,
            Ok(Ok(_))
        )
    }

    pub async fn wait_until_healthy(&self, timeout_secs: u64) -> Result<HealthSnapshot> {
        let deadline = Instant::now() + Duration::from_secs(timeout_secs);
        let interval = Duration::from_millis(self.config.health.poll_interval_ms);
        loop {
            let snap = self.snapshot().await;
            if snap.all_up() {
                tracing::info!(?snap, "all services healthy");
                return Ok(snap);
            }
            if Instant::now() >= deadline {
                return Err(anyhow!(
                    "services did not become healthy within {timeout_secs}s (last={snap:?})"
                ));
            }
            tracing::debug!(?snap, "still waiting for services");
            sleep(interval).await;
        }
    }
}
