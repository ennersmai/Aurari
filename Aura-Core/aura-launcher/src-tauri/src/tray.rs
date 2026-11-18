use std::sync::Arc;

use parking_lot::RwLock;
use tauri::image::Image;
use tauri::menu::{Menu, MenuBuilder, MenuEvent, MenuItemBuilder, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Runtime};
use crate::commands;
use crate::state::{IconVariant, LauncherState, StateMachine};

const TRAY_ID: &str = "aura-main";

const ICON_STOPPED: &[u8] = include_bytes!("../icons/tray-stopped-64.png");
const ICON_STARTING: &[u8] = include_bytes!("../icons/tray-starting-64.png");
const ICON_READY: &[u8] = include_bytes!("../icons/tray-ready-64.png");
const ICON_FAILED: &[u8] = include_bytes!("../icons/tray-failed-64.png");

pub type SharedState = Arc<RwLock<StateMachine>>;

pub fn setup<R: Runtime>(app: &AppHandle<R>, state: SharedState) -> tauri::Result<()> {
    let menu = build_menu(app, state.read().current())?;
    let icon = icon_for(state.read().current().icon_variant())?;

    TrayIconBuilder::with_id(TRAY_ID)
        .icon(icon)
        .menu(&menu)
        .tooltip("Aura — initializing…")
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| handle_menu_event(app, event))
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    let _ = commands::open_mission_control_internal(&app);
                });
            }
        })
        .build(app)?;

    Ok(())
}

pub fn refresh<R: Runtime>(app: &AppHandle<R>, state: &LauncherState) -> tauri::Result<()> {
    let Some(tray) = app.tray_by_id(TRAY_ID) else {
        return Ok(());
    };

    let icon = icon_for(state.icon_variant())?;
    tray.set_icon(Some(icon))?;
    tray.set_tooltip(Some(format!("Aura — {}", state.label())))?;

    let new_menu = build_menu(app, state)?;
    tray.set_menu(Some(new_menu))?;
    Ok(())
}

fn icon_for(variant: IconVariant) -> tauri::Result<Image<'static>> {
    let bytes: &'static [u8] = match variant {
        IconVariant::Stopped => ICON_STOPPED,
        IconVariant::Starting => ICON_STARTING,
        IconVariant::Ready => ICON_READY,
        IconVariant::Failed => ICON_FAILED,
    };
    Image::from_bytes(bytes)
}

fn build_menu<R: Runtime>(app: &AppHandle<R>, state: &LauncherState) -> tauri::Result<Menu<R>> {
    let status_label = format!("● {}", state.label());

    let status = MenuItemBuilder::with_id("status", status_label).enabled(false).build(app)?;
    let sep1 = PredefinedMenuItem::separator(app)?;

    let ready = matches!(state, LauncherState::Ready);
    let stopped = matches!(state, LauncherState::Stopped | LauncherState::Idle | LauncherState::Failed { .. });

    // Read config to check TTS requirements.
    let config = app.state::<crate::config::AuraConfig>();
    let tts_enabled = config.tts.enabled;
    let venv_missing = if tts_enabled {
        config.tts.tts_path.as_ref().map_or(true, |p| {
            !crate::tts_supervisor::TtsSupervisor::is_venv_ready(&p.display().to_string())
        })
    } else {
        false
    };

    let open_mc = MenuItemBuilder::with_id("open_mc", "Open Mission Control")
        .enabled(ready)
        .build(app)?;
    let open_ide = MenuItemBuilder::with_id("open_ide", "Open IDE").enabled(ready).build(app)?;
    let open_logs = MenuItemBuilder::with_id("open_logs", "Open Logs").build(app)?;
    let sep2 = PredefinedMenuItem::separator(app)?;

    let restart_backend = MenuItemBuilder::with_id("restart_backend", "Restart Backend Only")
        .enabled(ready)
        .build(app)?;
    let restart_all = MenuItemBuilder::with_id("restart_all", "Restart All")
        .enabled(ready || stopped)
        .build(app)?;
    let sync_rebuild = MenuItemBuilder::with_id("sync_rebuild", "Sync & Rebuild Core")
        .enabled(ready || stopped)
        .build(app)?;

    // --- Sovereign-native: "Start Aura" is always available when stopped ---
    let start_aura = MenuItemBuilder::with_id("start_aura", "Start Aura")
        .enabled(stopped)
        .build(app)?;

    let stop_aura = MenuItemBuilder::with_id("stop_aura", "Stop Aura").enabled(ready).build(app)?;
    let sep3 = PredefinedMenuItem::separator(app)?;

    let edit_env = MenuItemBuilder::with_id("edit_env", "Edit .env…").build(app)?;

    let quit = MenuItemBuilder::with_id("quit", "Quit Launcher").build(app)?;

    // TTS venv missing warning.
    let menu = if venv_missing {
        let tts_warning = MenuItemBuilder::with_id("tts_venv_missing", "TTS venv missing — run setup-env.ps1")
            .enabled(false)
            .build(app)?;
        let sep_tts = PredefinedMenuItem::separator(app)?;
        let sep4 = PredefinedMenuItem::separator(app)?;

        MenuBuilder::new(app)
            .item(&status)
            .item(&sep1)
            .item(&open_mc)
            .item(&open_ide)
            .item(&open_logs)
            .item(&sep2)
            .item(&restart_backend)
            .item(&restart_all)
            .item(&sync_rebuild)
            .item(&start_aura)
            .item(&stop_aura)
            .item(&sep3)
            .item(&edit_env)
            .item(&sep_tts)
            .item(&tts_warning)
            .item(&sep4)
            .item(&quit)
            .build()
    } else {
        let sep4 = PredefinedMenuItem::separator(app)?;
        let quit = MenuItemBuilder::with_id("quit", "Quit Launcher").build(app)?;

        MenuBuilder::new(app)
            .item(&status)
            .item(&sep1)
            .item(&open_mc)
            .item(&open_ide)
            .item(&open_logs)
            .item(&sep2)
            .item(&restart_backend)
            .item(&restart_all)
            .item(&sync_rebuild)
            .item(&start_aura)
            .item(&stop_aura)
            .item(&sep3)
            .item(&edit_env)
            .item(&sep4)
            .item(&quit)
            .build()
    };

    menu
}

fn handle_menu_event<R: Runtime>(app: &AppHandle<R>, event: MenuEvent) {
    let id = event.id().as_ref().to_string();
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = dispatch(&app, &id).await {
            tracing::error!(menu_item = %id, error = %e, "tray menu action failed");
        }
    });
}

async fn dispatch<R: Runtime>(app: &AppHandle<R>, id: &str) -> anyhow::Result<()> {
    match id {
        "open_mc" => commands::open_mission_control_internal(app)?,
        "open_ide" => commands::open_ide_internal(app)?,
        "open_logs" => commands::open_logs_internal(app)?,
        "restart_backend" => commands::restart_backend_internal(app).await?,
        "restart_all" => commands::restart_all_internal(app).await?,
        "sync_rebuild" => commands::sync_and_rebuild_core_internal(app).await?,
        "start_aura" => commands::start_aura_internal(app).await?,
        "stop_aura" => commands::stop_aura_internal(app).await?,
        "edit_env" => commands::open_env_editor_internal(app)?,
        "quit" => {
            commands::quit_launcher_internal(app).await;
        }
        _ => {}
    }
    Ok(())
}
