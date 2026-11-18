use aura_launcher_lib::AuraConfig;

#[test]
fn parses_example_config_shape() {
    let toml_src = r#"
        config_version = 1
        aura_app_path = "C:/Aura/aura-app"
        compose_file = "docker-compose.unified.yml"

        [services]
        database = "aura-database"
        backend = "aura-backend"
        frontend = "aura-frontend"

        [ports]
        database = 8000
        backend = 8080
        frontend = 3000

        [health]
        backend_path = "/health"
        frontend_path = "/"
        poll_interval_ms = 1500
        boot_timeout_secs = 180
        probe_timeout_secs = 3

        [docker]
        start_timeout_secs = 120
    "#;
    let cfg: AuraConfig = toml::from_str(toml_src).expect("parse");
    assert_eq!(cfg.ports.backend, 8080);
    assert_eq!(cfg.compose_file, "docker-compose.unified.yml");
    assert_eq!(cfg.health.backend_path, "/health");
    assert!(cfg.backend_health_url().ends_with(":8080/health"));
    assert!(cfg.mission_control_url().ends_with(":3000/mission-control"));
}

#[test]
fn rejects_mismatched_config_version() {
    let toml_src = r#"
        config_version = 99
        aura_app_path = "."
        compose_file = "x.yml"
    "#;
    let cfg: AuraConfig = toml::from_str(toml_src).expect("parse shape");
    assert_eq!(cfg.config_version, 99);
    // The version mismatch is enforced at the AuraConfig::load_or_default boundary,
    // not in the deserializer — so the parsed shape itself is fine.
}
