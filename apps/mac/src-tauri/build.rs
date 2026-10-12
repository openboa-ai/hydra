fn main() {
    let manifest = tauri_build::AppManifest::new().commands(&[
        "status",
        "control",
        "open_record",
        "request_quit",
    ]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("failed to build Hydra application context");
}
