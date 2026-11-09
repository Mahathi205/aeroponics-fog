"""Build and run the bundled iFogSim2 aeroponics scenario."""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIM_ROOT = Path(__file__).resolve().parent
TOOLKIT_ROOT = SIM_ROOT / "toolkit"
BUILD_ROOT = SIM_ROOT / "build"
CLASSES_DIR = BUILD_ROOT / "classes"
RESULTS_DIR = SIM_ROOT / "results"
MAIN_CLASS = "org.fog.test.perfeval.AeroponicsFogSimulation"


def _executable(name: str) -> str | None:
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / (name + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name) or shutil.which(name + ".exe")
    if found:
        return found

    # VS Code or Streamlit may have been launched before Windows refreshed PATH.
    # Discover the standard Eclipse Temurin install so an installed JDK still works.
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        install_root = program_files / "Eclipse Adoptium"
        candidates = sorted(install_root.glob("jdk-*"), reverse=True)
        executable = name + ".exe"
        for root in candidates:
            candidate = root / "bin" / executable
            if candidate.is_file():
                return str(candidate)
    return None


def java_status() -> dict[str, str | bool]:
    """Return whether a recent JDK (both java and javac) is available."""
    java = _executable("java")
    javac = _executable("javac")
    version = ""
    major = 0
    if java:
        try:
            checked = subprocess.run(
                [java, "-version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=5, check=False,
            )
            output = "\n".join((checked.stdout, checked.stderr))
            match = re.search(r'version "(?:1\.)?(\d+)', output)
            if match:
                major = int(match.group(1))
                version = f"Java {major}"
        except (OSError, subprocess.TimeoutExpired):
            pass
    available = bool(java and javac and major >= 21)
    return {
        "available": available,
        "java": java or "",
        "javac": javac or "",
        "version": version,
        "message": "" if available else "Install a Java 21+ JDK so both java and javac are available.",
    }


def _all_sources() -> list[Path]:
    roots = [TOOLKIT_ROOT / "src", SIM_ROOT / "src"]
    sources = [path for root in roots for path in root.rglob("*.java")]
    # This optional CloudSim container policy in the bundled toolkit release
    # refers to an omitted superclass. The aeroponics model does not use it.
    # Exclude that orphaned example so it cannot block compilation of iFogSim.
    orphaned_policy = "PowerContainerVmAllocationPolicyMigrationStaticThresholdMCUnderUtilized.java"
    sources = [path for path in sources if path.name != orphaned_policy]
    if not sources:
        raise RuntimeError("No Java sources found. The bundled iFogSim toolkit is missing.")
    return sorted(sources)


def _all_jars() -> list[Path]:
    jars = sorted((TOOLKIT_ROOT / "jars").rglob("*.jar"))
    if not jars:
        raise RuntimeError("No iFogSim libraries found under ifogsim/toolkit/jars.")
    return jars


def _classpath(jars: list[Path]) -> str:
    paths = [str(CLASSES_DIR), *(str(path) for path in jars)]
    return os.pathsep.join(paths)


def _needs_build(sources: list[Path], jars: list[Path], force: bool) -> bool:
    stamp = BUILD_ROOT / ".compiled"
    if force or not stamp.exists() or not CLASSES_DIR.exists():
        return True
    def input_mtime(path: Path) -> float:
        # The Codex workspace path plus nested iFogSim package names can exceed
        # Windows' legacy MAX_PATH. Use the extended path form for stat calls.
        raw_path = os.path.abspath(os.fspath(path))
        if os.name == "nt" and not raw_path.startswith("\\\\?\\"):
            raw_path = "\\\\?\\" + raw_path
        return os.stat(raw_path).st_mtime

    latest_input = max(input_mtime(path) for path in [*sources, *jars])
    return latest_input > stamp.stat().st_mtime


def _compile(javac: str, sources: list[Path], jars: list[Path], force: bool) -> str:
    if not _needs_build(sources, jars, force):
        return "iFogSim classes are up to date."

    CLASSES_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    arg_file = BUILD_ROOT / "java-sources.args"
    # Forward slashes are accepted by javac on Windows and avoid path escaping
    # in the compiler's argument-file syntax.
    arg_file.write_text(
        "\n".join('"' + path.resolve().as_posix().replace('"', '\\"') + '"' for path in sources),
        encoding="utf-8",
    )
    command = [
        javac,
        "-encoding",
        "UTF-8",
        "-cp",
        os.pathsep.join(str(path) for path in jars),
        "-d",
        str(CLASSES_DIR),
        "@" + str(arg_file),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode:
        raise RuntimeError("iFogSim could not be compiled.\n" + (output or "javac returned an error."))
    (BUILD_ROOT / ".compiled").write_text("ok\n", encoding="utf-8")
    return output or f"Compiled {len(sources)} Java source files."


def _read_result(mode: str) -> dict[str, str] | None:
    result_file = RESULTS_DIR / f"ifogsim_{mode}.csv"
    if not result_file.exists():
        return None
    with result_file.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-1] if rows else None


def read_results() -> list[dict[str, str]]:
    """Read the most recent fog and cloud output rows for the dashboard."""
    return [row for mode in ("fog", "cloud") if (row := _read_result(mode)) is not None]


def read_sensor_readings(mode: str = "fog") -> list[dict[str, str]]:
    """Read per-emission virtual humidity samples from an iFogSim scenario."""
    if mode not in {"fog", "cloud"}:
        raise ValueError("Sensor readings are available for fog or cloud scenarios.")
    readings_file = RESULTS_DIR / f"ifogsim_sensor_readings_{mode}.csv"
    if not readings_file.exists():
        return []
    with readings_file.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run_simulation(
    mode: str = "both",
    sensor_count: int = 3,
    wan_latency_ms: int = 100,
    simulation_seconds: int = 300,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Compile the bundled toolkit if needed and execute the requested case."""
    if mode not in {"fog", "cloud", "both"}:
        raise ValueError("Mode must be fog, cloud, or both.")
    if not 1 <= sensor_count <= 16:
        raise ValueError("Sensor zones must be between 1 and 16.")
    if not 1 <= wan_latency_ms <= 1000:
        raise ValueError("WAN latency must be between 1 and 1000 ms.")
    if not 30 <= simulation_seconds <= 3600:
        raise ValueError("Simulation duration must be between 30 and 3600 seconds.")

    status = java_status()
    if not status["available"]:
        raise RuntimeError(
            "A Java 21+ JDK is needed to run the bundled iFogSim2 source. Install a recent JDK, then reopen the terminal "
            "so JAVA_HOME or PATH includes both java and javac."
        )

    sources = _all_sources()
    jars = _all_jars()
    build_message = _compile(str(status["javac"]), sources, jars, force_rebuild)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    classpath = _classpath(jars)
    modes = ("fog", "cloud") if mode == "both" else (mode,)
    runs: list[dict[str, Any]] = []

    for scenario in modes:
        command = [
            str(status["java"]),
            f"-Daeroponics.resultsDir={RESULTS_DIR}",
            "-cp",
            classpath,
            MAIN_CLASS,
            scenario,
            str(sensor_count),
            str(wan_latency_ms),
            str(simulation_seconds),
        ]
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        if completed.returncode:
            raise RuntimeError(f"The {scenario} iFogSim run failed.\n{output or 'Java returned an error.'}")
        row = _read_result(scenario)
        if row is None:
            raise RuntimeError(
                f"The {scenario} process ended without a result file. Check the Java output.\n{output}"
            )
        runs.append({"scenario": scenario, "result": row, "output": output})

    return {"build": build_message, "runs": runs, "results": read_results()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the aeroponics iFogSim2 digital twin.")
    parser.add_argument("--mode", choices=("fog", "cloud", "both"), default="both")
    parser.add_argument("--sensors", type=int, default=3, help="Number of sensor/pump zones (1-16).")
    parser.add_argument("--wan-ms", type=int, default=100, help="Gateway-to-cloud one-way delay.")
    parser.add_argument("--seconds", type=int, default=300, help="Simulated duration (30-3600 seconds).")
    parser.add_argument("--rebuild", action="store_true", help="Force recompilation of iFogSim.")
    args = parser.parse_args()
    try:
        outcome = run_simulation(args.mode, args.sensors, args.wan_ms, args.seconds, args.rebuild)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(outcome["build"])
    for run in outcome["runs"]:
        print(run["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
