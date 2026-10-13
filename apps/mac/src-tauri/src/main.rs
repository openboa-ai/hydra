mod process;
mod protocol;

use process::{bounded_output, LaunchConfig};
use protocol::{Action, RecordKind, Snapshot, Target};
use serde::Serialize;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri::{Emitter, Manager};
use tokio::sync::Mutex;

#[derive(Clone, Debug, Serialize)]
struct BridgeError {
    code: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<Snapshot>,
}

impl BridgeError {
    fn new(code: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            status: None,
        }
    }
    fn with_status(code: impl Into<String>, status: Option<Snapshot>) -> Self {
        Self {
            code: code.into(),
            status,
        }
    }
}

struct Bridge {
    launch: Result<LaunchConfig, &'static str>,
    mutation: Mutex<()>,
    local_read: Mutex<()>,
    remote_read: Mutex<()>,
    record_open: Mutex<()>,
    quitting: AtomicBool,
    exit_confirmed: AtomicBool,
}

impl Bridge {
    fn new() -> Self {
        Self {
            launch: LaunchConfig::from_arguments(std::env::args_os().skip(1)),
            mutation: Mutex::new(()),
            local_read: Mutex::new(()),
            remote_read: Mutex::new(()),
            record_open: Mutex::new(()),
            quitting: AtomicBool::new(false),
            exit_confirmed: AtomicBool::new(false),
        }
    }

    async fn call(
        &self,
        action: Option<Action>,
        target: Option<&Target>,
        refresh: bool,
    ) -> Result<Snapshot, BridgeError> {
        let launch = self
            .launch
            .as_ref()
            .map_err(|code| BridgeError::new(*code))?;
        let duration = if refresh {
            Duration::from_secs(60)
        } else if action.is_some() {
            Duration::from_secs(30)
        } else {
            Duration::from_secs(15)
        };
        let bytes = bounded_output(launch.command(action, target, refresh), duration)
            .await
            .map_err(BridgeError::new)?;
        Snapshot::parse(&bytes).map_err(BridgeError::new)
    }

    async fn snapshot(&self, refresh: bool) -> Result<Snapshot, BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        // Remote reads cannot hold the mutation lane needed by Pause and Stop.
        let _guard = if refresh {
            self.remote_read.lock().await
        } else {
            self.local_read.lock().await
        };
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        self.call(None, None, refresh).await
    }

    async fn open_record(
        &self,
        repository: &str,
        kind: RecordKind,
        issue: Option<u64>,
        expected_pr: Option<u64>,
    ) -> Result<(), BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let _guard = self.record_open.lock().await;
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let snapshot = self.snapshot(!matches!(kind, RecordKind::Chat)).await?;
        let url = protocol::selected_record(&snapshot, repository, kind, issue, expected_pr)
            .map_err(BridgeError::new)?;
        process::open_record_url(&url)
            .await
            .map_err(BridgeError::new)
    }

    async fn mutate_locked(
        &self,
        action: Action,
        target: &Target,
    ) -> Result<Snapshot, BridgeError> {
        self.launch
            .as_ref()
            .map_err(|code| BridgeError::new(*code))?;
        if let Target::Project { repository } = target {
            if !protocol::repository_valid(repository) {
                return Err(BridgeError::new("project_unregistered"));
            }
            let snapshot = self.call(None, None, false).await?;
            if snapshot.project(repository).is_none() {
                return Err(BridgeError::new("project_unregistered"));
            }
        }
        match self.call(Some(action), Some(target), false).await {
            Ok(snapshot) if snapshot.acknowledges(action, target) => Ok(snapshot),
            Err(error) if error.code == "backend_unavailable" => Err(error),
            Err(error) if error.code == "unsupported_runtime" => {
                // An incompatible response cannot confirm whether the effect
                // happened. Preserve its cause and reconcile without retrying.
                let status = self.call(None, None, false).await.ok();
                Err(BridgeError::with_status("unsupported_runtime", status))
            }
            _ => {
                // The effect may have happened before the response was lost.
                // Reconcile once; never resend the mutation automatically.
                let status = self.call(None, None, false).await.ok();
                Err(BridgeError::with_status("mutation_response_lost", status))
            }
        }
    }

    async fn mutate(&self, action: Action, target: Target) -> Result<Snapshot, BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let _guard = self.mutation.lock().await;
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        self.mutate_locked(action, &target).await
    }
}

fn main_window(window: &tauri::WebviewWindow) -> Result<(), BridgeError> {
    if window.label() == "main" && window.url().is_ok_and(|url| bundled_navigation(&url)) {
        Ok(())
    } else {
        Err(BridgeError::new("window_not_authorized"))
    }
}

#[tauri::command]
async fn status(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Bridge>>,
    refresh: bool,
) -> Result<Snapshot, BridgeError> {
    main_window(&window)?;
    state.snapshot(refresh).await
}

#[tauri::command]
async fn control(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Bridge>>,
    action: Action,
    target: Target,
) -> Result<Snapshot, BridgeError> {
    main_window(&window)?;
    state.mutate(action, target).await
}

#[tauri::command(rename_all = "camelCase")]
async fn open_record(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Bridge>>,
    repository: String,
    kind: RecordKind,
    issue: Option<u64>,
    expected_pr: Option<u64>,
) -> Result<(), BridgeError> {
    main_window(&window)?;
    if !protocol::repository_valid(&repository) {
        return Err(BridgeError::new("project_unregistered"));
    }
    state
        .open_record(&repository, kind, issue, expected_pr)
        .await
}

#[derive(Clone, Serialize)]
struct QuitEvent {
    state: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<Snapshot>,
}

struct QuitAttempt<'a>(&'a AtomicBool);
impl Drop for QuitAttempt<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

fn show_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

async fn quit_flow(app: tauri::AppHandle) -> Result<Snapshot, BridgeError> {
    let bridge = app.state::<Arc<Bridge>>().inner().clone();
    if bridge.exit_confirmed.load(Ordering::Acquire) {
        return Err(BridgeError::new("quit_in_progress"));
    }
    if bridge
        .quitting
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Err(BridgeError::new("quit_in_progress"));
    }
    let _attempt = QuitAttempt(&bridge.quitting);
    show_window(&app);
    let _ = app.emit_to(
        "main",
        "hydra:quit",
        QuitEvent {
            state: "stopping",
            code: None,
            status: None,
        },
    );
    let _guard = bridge.mutation.lock().await;
    let result = async {
        let stopped = match bridge.mutate_locked(Action::Stop, &Target::All).await {
            Ok(snapshot) => snapshot,
            Err(error) => match error.status {
                Some(snapshot) => snapshot,
                None => return Err(error),
            },
        };
        // Fence new commands, then join every lane that can own a child before
        // accepting the final observation. Lock order matches record -> read.
        let _record = bridge.record_open.lock().await;
        let _local = bridge.local_read.lock().await;
        let _remote = bridge.remote_read.lock().await;
        // A fresh read is required even after an apparently successful Stop.
        // Source support or a free local lock alone never authorizes Quit.
        let snapshot = bridge.call(None, None, true).await?;
        if !snapshot.permits_quit()
            || !snapshot.same_targets(&stopped)
            || !snapshot.same_runtime(&stopped)
            || stopped.revision.is_none()
            || snapshot.revision < stopped.revision
        {
            return Err(BridgeError::with_status("quit_blocked", Some(snapshot)));
        }
        Ok(snapshot)
    }
    .await;
    match result {
        Ok(snapshot) => {
            bridge.exit_confirmed.store(true, Ordering::Release);
            app.exit(0);
            Ok(snapshot)
        }
        Err(error) => {
            show_window(&app);
            let _ = app.emit_to(
                "main",
                "hydra:quit",
                QuitEvent {
                    state: "blocked",
                    code: Some(error.code.clone()),
                    status: error.status.clone(),
                },
            );
            Err(error)
        }
    }
}

#[tauri::command]
async fn request_quit(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
) -> Result<Snapshot, BridgeError> {
    main_window(&window)?;
    quit_flow(app).await
}

fn launch_quit(app: &tauri::AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let _ = quit_flow(app).await;
    });
}

fn bundled_navigation(url: &tauri::Url) -> bool {
    url.scheme() == "tauri"
        && url.host_str() == Some("localhost")
        // Tauri uses the bare custom-scheme origin for its index document.
        && matches!(url.path(), "" | "/" | "/index.html")
        && url.query().is_none()
        && url.fragment().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.port().is_none()
}

fn tray_image() -> tauri::image::Image<'static> {
    // Three horizontal control tracks form a functional operations symbol.
    let mut pixels = vec![0; 18 * 18 * 4];
    for (y, knob) in [(4, 6), (9, 12), (14, 8)] {
        for x in 2..16 {
            for dy in 0..2 {
                pixels[((y + dy) * 18 + x) * 4 + 3] = 255;
            }
        }
        for yy in y - 1..=y + 2 {
            for xx in knob - 1..=knob + 1 {
                pixels[(yy * 18 + xx) * 4 + 3] = 255;
            }
        }
    }
    tauri::image::Image::new_owned(pixels, 18, 18)
}

fn main() {
    let application = tauri::Builder::default()
        .manage(Arc::new(Bridge::new()))
        .invoke_handler(tauri::generate_handler![
            status,
            control,
            open_record,
            request_quit
        ])
        .setup(|app| {
            let show =
                tauri::menu::MenuItem::with_id(app, "app-show", "Show Hydra", true, None::<&str>)?;
            let quit = tauri::menu::MenuItem::with_id(
                app,
                "app-quit",
                "Stop All and Quit Hydra",
                true,
                Some("CmdOrCtrl+Q"),
            )?;
            let submenu = tauri::menu::Submenu::with_items(app, "Hydra", true, &[&show, &quit])?;
            let app_menu = tauri::menu::Menu::with_items(app, &[&submenu])?;
            app.set_menu(app_menu)?;
            let tray_show =
                tauri::menu::MenuItem::with_id(app, "tray-show", "Show Hydra", true, None::<&str>)?;
            let tray_quit = tauri::menu::MenuItem::with_id(
                app,
                "tray-quit",
                "Stop All and Quit Hydra",
                true,
                None::<&str>,
            )?;
            let tray_menu = tauri::menu::Menu::with_items(app, &[&tray_show, &tray_quit])?;
            tauri::tray::TrayIconBuilder::with_id("hydra-operations")
                .icon(tray_image())
                .icon_as_template(true)
                .tooltip("Hydra operating controls")
                .menu(&tray_menu)
                .show_menu_on_left_click(true)
                .build(app)?;
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("Hydra")
            .inner_size(720.0, 820.0)
            .min_inner_size(480.0, 520.0)
            .devtools(false)
            .disable_drag_drop_handler()
            .center()
            .on_navigation(bundled_navigation)
            .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
            .on_permission_request(|_, _| tauri::webview::PermissionResponse::Deny)
            .on_download(|_, _| false)
            .build()?;
            Ok(())
        })
        .on_menu_event(|app, event| match event.id.as_ref() {
            "app-show" | "tray-show" => show_window(app),
            "app-quit" | "tray-quit" => launch_quit(app),
            _ => {}
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!());
    match application {
        Ok(app) => app.run(|handle, event| {
            #[cfg(target_os = "macos")]
            if matches!(&event, tauri::RunEvent::Reopen { .. }) {
                show_window(handle);
            }
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if !handle
                    .state::<Arc<Bridge>>()
                    .exit_confirmed
                    .load(Ordering::Acquire)
                {
                    api.prevent_exit();
                    launch_quit(handle);
                }
            }
        }),
        Err(_) => eprintln!("Hydra could not initialize its application window."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn queued_refresh_cannot_spawn_after_quit_fence() {
        let bridge = Arc::new(Bridge::new());
        let guard = bridge.remote_read.lock().await;
        let pending_bridge = bridge.clone();
        let pending = tokio::spawn(async move { pending_bridge.snapshot(true).await });
        tokio::task::yield_now().await;
        bridge.quitting.store(true, Ordering::Release);
        drop(guard);
        assert_eq!(pending.await.unwrap().unwrap_err().code, "quit_in_progress");
        bridge.quitting.store(false, Ordering::Release);
        bridge.exit_confirmed.store(true, Ordering::Release);
        assert_eq!(
            bridge
                .mutate(Action::Start, Target::All)
                .await
                .unwrap_err()
                .code,
            "quit_in_progress"
        );
    }
    #[test]
    fn navigation_only_accepts_bundled_document() {
        for input in [
            "tauri://localhost",
            "tauri://localhost/",
            "tauri://localhost/index.html",
        ] {
            assert!(bundled_navigation(&tauri::Url::parse(input).unwrap()));
        }
        for input in [
            "https://example.test",
            "tauri://other/index.html",
            "tauri://localhost/file",
            "tauri://localhost/?command=stop",
            "tauri://localhost#fragment",
            "tauri://user@localhost",
            "tauri://user:password@localhost/index.html",
            "tauri://localhost:80",
            "http://tauri.localhost",
            "file:///tmp/index.html",
        ] {
            assert!(!bundled_navigation(&tauri::Url::parse(input).unwrap()));
        }
    }
}
