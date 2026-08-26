// Liquidity Analysis Engine — shell Tauri.
// Avvia liquidity-server.exe (sidecar PyInstaller: FastAPI + motore analisi)
// sulla porta 8000 e lo termina all'uscita. Pattern ricalcato da DegenScan.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// Fallback: percorso Python diretto (dev / macchina sviluppatore Windows).
#[cfg(windows)]
const PYTHON_EXE: &str = r"C:\Claude\_trading\backend\.venv\Scripts\python.exe";
#[cfg(not(windows))]
const PYTHON_EXE: &str = "python3";

#[cfg(windows)]
const SIDECAR_NAME: &str = "liquidity-server.exe";
#[cfg(not(windows))]
const SIDECAR_NAME: &str = "liquidity-server";

struct ApiServer(Mutex<Option<Child>>);

/// Cerca il server da avviare:
/// 1. sidecar nella cartella resources (build installato/portabile)
/// 2. sidecar accanto all'exe, o in .\binaries\
/// 3. app_entry.py via Python (sviluppo)
fn find_and_spawn_server(resource_dir: Option<PathBuf>) -> Option<Child> {
    let sidecar_candidates: Vec<PathBuf> = {
        let mut v = Vec::new();
        if let Some(ref res) = resource_dir {
            v.push(res.join("binaries").join(SIDECAR_NAME));
            v.push(res.join(SIDECAR_NAME));
        }
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                v.push(dir.join(SIDECAR_NAME));
                v.push(dir.join("binaries").join(SIDECAR_NAME));
                if let Some(contents_dir) = dir.parent() {
                    v.push(contents_dir.join("Resources").join("binaries").join(SIDECAR_NAME));
                }
            }
        }
        v
    };

    for bin in &sidecar_candidates {
        if bin.exists() {
            let mut cmd = Command::new(bin);
            cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
            if let Some(dir) = bin.parent() {
                cmd.current_dir(dir);
            }
            #[cfg(windows)]
            cmd.creation_flags(CREATE_NO_WINDOW);
            match cmd.spawn() {
                Ok(child) => {
                    eprintln!("[tauri] server avviato (sidecar): {}", bin.display());
                    return Some(child);
                }
                Err(e) => eprintln!("[tauri] sidecar errore {}: {e}", bin.display()),
            }
        }
    }

    // — Fallback Python (sviluppo) —
    let py_candidates: Vec<PathBuf> = vec![PathBuf::from(r"C:\Claude\_trading\backend\app_entry.py")];

    for script in &py_candidates {
        if script.exists() {
            let mut cmd = Command::new(PYTHON_EXE);
            cmd.arg(script)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            if let Some(dir) = script.parent() {
                cmd.current_dir(dir);
            }
            match cmd.spawn() {
                Ok(child) => {
                    eprintln!("[tauri] server avviato (Python): {}", script.display());
                    return Some(child);
                }
                Err(e) => eprintln!("[tauri] Python errore {}: {e}", script.display()),
            }
        }
    }

    eprintln!("[tauri] impossibile avviare il server dati");
    None
}

fn port_in_use() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8000".parse().unwrap(),
        std::time::Duration::from_millis(300),
    )
    .is_ok()
}

fn kill_api_server(state: &ApiServer) {
    if let Ok(mut guard) = state.0.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
            eprintln!("[tauri] server terminato");
        }
    }
}

fn main() {
    tauri::Builder::default()
        .manage(ApiServer(Mutex::new(None)))
        .setup(|app| {
            let res_dir = app.path().resource_dir().ok();
            let child = if port_in_use() {
                eprintln!("[tauri] porta 8000 già in uso, salto avvio server");
                None
            } else {
                find_and_spawn_server(res_dir)
            };
            *app.state::<ApiServer>().0.lock().unwrap() = child;

            if let Some(window) = app.get_webview_window("main") {
                std::thread::spawn(move || {
                    for _ in 0..60 {
                        if port_in_use() {
                            let _ = window.navigate("http://127.0.0.1:8000".parse().unwrap());
                            return;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(500));
                    }
                    eprintln!("[tauri] il server non ha risposto entro 30s");
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill_api_server(window.state::<ApiServer>().inner());
            }
        })
        .build(tauri::generate_context!())
        .expect("errore avvio applicazione Tauri")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                kill_api_server(app_handle.state::<ApiServer>().inner());
            }
        });
}
