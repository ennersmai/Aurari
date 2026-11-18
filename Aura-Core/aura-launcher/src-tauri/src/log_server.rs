//! Tiny SSE (Server-Sent Events) server that streams system logs to the
//! browser-based frontend. Since the Next.js frontend runs in Docker (not
//! inside a Tauri WebView), Tauri's `emit` cannot reach it directly.
//!
//! This module starts a TCP listener on `127.0.0.1:9876` and serves an
//! `text/event-stream` endpoint at `/logs/stream`. Every log line pushed
//! through the broadcast channel is forwarded to all connected browsers.

use std::net::TcpListener;
use std::thread;

use tokio::sync::broadcast;

use crate::tts_supervisor::SystemLogPayload;

/// Global broadcast channel for log lines.
static SENDER: std::sync::OnceLock<broadcast::Sender<String>> = std::sync::OnceLock::new();

/// Initialise the broadcast channel and start the SSE listener thread.
/// Call once during launcher startup.
pub fn start() {
    let (tx, _rx) = broadcast::channel::<String>(512);
    SENDER.set(tx).ok();

    thread::spawn(move || {
        let listener = match TcpListener::bind("127.0.0.1:9876") {
            Ok(l) => {
                tracing::info!("log SSE server listening on http://127.0.0.1:9876/logs/stream");
                l
            }
            Err(e) => {
                tracing::warn!(error = %e, "could not bind log SSE port 9876");
                return;
            }
        };

        for stream in listener.incoming() {
            match stream {
                Ok(stream) => {
                    let rx = SENDER.get().unwrap().subscribe();
                    thread::spawn(move || serve_sse(stream, rx));
                }
                Err(e) => {
                    tracing::error!(error = %e, "log SSE accept error");
                }
            }
        }
    });
}

/// Push a log line to all connected SSE clients.
pub fn broadcast(payload: &SystemLogPayload) {
    if let Some(tx) = SENDER.get() {
        if let Ok(json) = serde_json::to_string(payload) {
            let _ = tx.send(json);
        }
    }
}

/// Serve a single SSE connection. Blocks until the client disconnects.
fn serve_sse(mut stream: std::net::TcpStream, mut rx: broadcast::Receiver<String>) {
    use std::io::Write;

    // Send HTTP headers for SSE.
    let headers = "HTTP/1.1 200 OK\r\n\
                    Content-Type: text/event-stream\r\n\
                    Cache-Control: no-cache\r\n\
                    Connection: keep-alive\r\n\
                    Access-Control-Allow-Origin: *\r\n\
                    \r\n";
    if stream.write_all(headers.as_bytes()).is_err() {
        return;
    }
    let _ = stream.flush();

    // Stream log lines as SSE events (blocking receive — we're on a dedicated thread).
    loop {
        match rx.blocking_recv() {
            Ok(line) => {
                let event = format!("data: {}\n\n", line);
                if stream.write_all(event.as_bytes()).is_err() {
                    break;
                }
                let _ = stream.flush();
            }
            Err(broadcast::error::RecvError::Lagged(n)) => {
                tracing::warn!(skipped = n, "SSE client lagging");
            }
            Err(broadcast::error::RecvError::Closed) => break,
        }
    }
}
