from __future__ import annotations

from tools import release_builder


def test_inno_preserves_client_configs_and_updates_managed_catalog(tmp_path):
    build_root = tmp_path / "build"
    app_dir = build_root / "app"
    out_dir = tmp_path / "out"
    app_dir.mkdir(parents=True)
    out_dir.mkdir()

    script = release_builder._write_inno(
        build_root,
        app_dir,
        out_dir,
        "CLIENTE",
        icon=True,
    )
    text = script.read_text(encoding="utf-8")

    assert "CloseApplications=yes" in text
    assert "RestartApplications=no" in text
    assert "SetupLogging=yes" in text
    assert 'Excludes: "configs\\*"' in text
    assert not [
        (index, ord(char))
        for index, char in enumerate(text)
        if ord(char) < 32 and char not in "\r\n"
    ]

    format_line = next(
        line for line in text.splitlines() if "configs\\formatos\\*" in line
    )
    forms_line = next(
        line for line in text.splitlines() if "configs\\formularios\\*" in line
    )
    system_line = next(
        line for line in text.splitlines() if "configs\\sistema\\*" in line
    )

    assert "onlyifdoesntexist" not in format_line
    assert "onlyifdoesntexist" in forms_line
    assert "onlyifdoesntexist" in system_line
    assert "skipifsourcedoesntexist" in forms_line
    assert "skipifsourcedoesntexist" in system_line


def test_real_pyinstaller_command_declares_critical_runtime_modules(
    tmp_path,
    monkeypatch,
):
    work = tmp_path / "work"
    work.mkdir()
    captured = []

    monkeypatch.setattr(release_builder, "_pyinstaller", lambda: "pyinstaller")

    def fake_run(command, *, cwd, log, required=True):
        captured.append(command)
        output = cwd / "dist" / "LectorPrueba.exe"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"MZ" + b"0" * 2048)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(release_builder, "_run", fake_run)

    output = release_builder._build_exe(
        work,
        "main.py",
        "LectorPrueba",
        tmp_path / "build.log",
    )

    command = captured[0]
    assert output.is_file()
    for module in (
        "assets.runtime.hardened.process_supervisor",
        "assets.runtime.hardened.safe_clipboard",
        "assets.runtime.hardened.scan_quality",
    ):
        assert module in command


def test_template_copy_excludes_generated_and_diagnostic_files(tmp_path, monkeypatch):
    template = tmp_path / "template"
    (template / "assets").mkdir(parents=True)
    (template / "assets" / "runtime.py").write_text("ok", encoding="utf-8")
    for directory in ("build", "dist", "logs", "diagnosticos", "__pycache__"):
        target = template / directory
        target.mkdir()
        (target / "generated.txt").write_text("no", encoding="utf-8")
    (template / "old.spec").write_text("no", encoding="utf-8")

    monkeypatch.setattr(release_builder, "TEMPLATE", template)
    work = tmp_path / "work"
    release_builder._copy_template(work)

    assert (work / "assets" / "runtime.py").is_file()
    for directory in ("build", "dist", "logs", "diagnosticos", "__pycache__"):
        assert not (work / directory).exists()
    assert not (work / "old.spec").exists()
