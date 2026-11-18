use aura_launcher_lib::state::{IconVariant, LauncherState, StateMachine};

#[test]
fn defaults_to_idle() {
    let sm = StateMachine::new();
    assert_eq!(sm.current(), &LauncherState::Idle);
    assert_eq!(sm.current().icon_variant(), IconVariant::Stopped);
}

#[test]
fn happy_path_transitions() {
    let mut sm = StateMachine::new();
    for next in [
        LauncherState::DockerStarting,
        LauncherState::ComposeUp,
        LauncherState::HealthChecking,
        LauncherState::Ready,
    ] {
        sm.transition(next.clone());
        assert_eq!(sm.current(), &next);
    }
    assert_eq!(sm.current().icon_variant(), IconVariant::Ready);
}

#[test]
fn failed_state_carries_reason() {
    let mut sm = StateMachine::new();
    sm.transition(LauncherState::Failed { reason: "docker exploded".into() });
    assert!(sm.current().is_terminal_failure());
    assert!(sm.current().label().contains("docker exploded"));
    assert_eq!(sm.current().icon_variant(), IconVariant::Failed);
}
