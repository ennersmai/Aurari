//! Smoke-test the health prober against an in-process HTTP server. Validates
//! that the concurrent join probes all three services, treats only 2xx as up,
//! and surfaces a HealthSnapshot payload the UI can consume.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use aura_launcher_lib::config::AuraConfig;
use aura_launcher_lib::health::HealthChecker;
use tokio::net::TcpListener;

async fn bind_localhost() -> (TcpListener, u16) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    (listener, port)
}

async fn serve_forever(listener: TcpListener, status_line: &'static str, body: &'static str) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let resp = format!(
        "HTTP/1.1 {status_line}\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    loop {
        let (mut sock, _) = match listener.accept().await {
            Ok(v) => v,
            Err(_) => break,
        };
        let resp = resp.clone();
        tokio::spawn(async move {
            let mut buf = [0u8; 1024];
            let _ = sock.read(&mut buf).await;
            let _ = sock.write_all(resp.as_bytes()).await;
            let _ = sock.shutdown().await;
        });
    }
}

fn config_with_ports(backend: u16, frontend: u16, db: u16) -> AuraConfig {
    let mut cfg = AuraConfig::default();
    cfg.aura_app_path = PathBuf::from(".");
    cfg.ports.backend = backend;
    cfg.ports.frontend = frontend;
    cfg.ports.database = db;
    cfg.health.poll_interval_ms = 100;
    cfg.health.probe_timeout_secs = 1;
    cfg
}

#[tokio::test]
async fn snapshot_reports_all_up_when_all_endpoints_serve_200() {
    let (backend_listener, backend_port) = bind_localhost().await;
    let (frontend_listener, frontend_port) = bind_localhost().await;
    let (db_listener, db_port) = bind_localhost().await;

    // DB just needs an open TCP socket; keep the listener alive for the test.
    let _db_keepalive = Arc::new(db_listener);

    tokio::spawn(serve_forever(backend_listener, "200 OK", "{\"ok\":true}"));
    tokio::spawn(serve_forever(frontend_listener, "200 OK", "<html></html>"));

    let cfg = config_with_ports(backend_port, frontend_port, db_port);
    let checker = HealthChecker::new(cfg);
    // Tiny sleep to let the spawn'd servers reach `accept`.
    tokio::time::sleep(Duration::from_millis(50)).await;
    let snap = checker.snapshot().await;
    assert!(snap.backend, "backend should be up");
    assert!(snap.frontend, "frontend should be up");
    assert!(snap.database, "database tcp should be open");
    assert!(snap.all_up());
}

#[tokio::test]
async fn snapshot_reports_backend_down_on_500() {
    let (backend_listener, backend_port) = bind_localhost().await;
    let (frontend_listener, frontend_port) = bind_localhost().await;
    let (db_listener, db_port) = bind_localhost().await;
    let _db_keepalive = Arc::new(db_listener);

    tokio::spawn(serve_forever(backend_listener, "500 Internal Server Error", "boom"));
    tokio::spawn(serve_forever(frontend_listener, "200 OK", "<html></html>"));

    let cfg = config_with_ports(backend_port, frontend_port, db_port);
    let checker = HealthChecker::new(cfg);
    tokio::time::sleep(Duration::from_millis(50)).await;
    let snap = checker.snapshot().await;
    assert!(!snap.backend, "5xx must not count as healthy");
    assert!(snap.frontend);
    assert!(!snap.all_up());
}

#[tokio::test]
async fn snapshot_reports_db_down_when_port_unbound() {
    // Bind then drop to free the port — guarantees nothing is listening.
    let (l, db_port) = bind_localhost().await;
    drop(l);

    let (backend_l, backend_port) = bind_localhost().await;
    let (frontend_l, frontend_port) = bind_localhost().await;
    tokio::spawn(serve_forever(backend_l, "200 OK", "ok"));
    tokio::spawn(serve_forever(frontend_l, "200 OK", "ok"));

    let cfg = config_with_ports(backend_port, frontend_port, db_port);
    let checker = HealthChecker::new(cfg);
    tokio::time::sleep(Duration::from_millis(50)).await;
    let snap = checker.snapshot().await;
    assert!(!snap.database, "tcp probe should fail on closed port");
}
