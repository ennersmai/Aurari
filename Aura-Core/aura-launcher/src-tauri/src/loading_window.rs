//! Native loading window for Aura Launcher
//! Shows a simple dialog with progress during Docker startup

use tauri::{AppHandle, Emitter, Manager, Runtime, WebviewWindowBuilder};

/// Create and show the loading window
pub fn show<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let window = WebviewWindowBuilder::new(
        app,
        "loading",
        tauri::WebviewUrl::App("loading.html".into()),
    )
    .title("Aura")
    .inner_size(400.0, 200.0)
    .resizable(false)
    .decorations(false)
    .transparent(true)
    .center()
    .always_on_top(true)
    .build()?;
    
    window.show()?;
    Ok(())
}

/// Update the loading window with current status
pub fn update_status<R: Runtime>(app: &AppHandle<R>, status: &str) {
    if let Some(window) = app.get_webview_window("loading") {
        let _ = window.emit("status-update", status);
    }
}

/// Close the loading window
pub fn close<R: Runtime>(app: &AppHandle<R>) {
    if let Some(window) = app.get_webview_window("loading") {
        let _ = window.close();
    }
}
