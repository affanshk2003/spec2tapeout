@echo off
REM ============================================================
REM  run_rtl2gds.bat — RTL-to-GDS Pipeline Launcher
REM  ASU Spec2Tapeout | ICLAD 2025 | Affan
REM
REM  Usage:
REM    Double-click this file, OR run from PowerShell:
REM      .\run_rtl2gds.bat p1
REM
REM  Argument (optional):
REM    Problem number: p1, p5, p7, p8, p9  (default: p1)
REM
REM  What this does:
REM    1. Starts the ORFS Docker container
REM    2. Mounts this folder as /workspace inside the container
REM    3. Runs the full RTL → Synthesis → P&R → GDS flow
REM    4. Copies GDS + report back to this folder
REM ============================================================

SET DOCKER="C:\Program Files\Docker\Docker\resources\bin\docker.exe"
SET PROJECT_DIR=%~dp0
SET PROJECT_DIR=%PROJECT_DIR:~0,-1%
SET IMAGE=openroad/orfs

REM Problem to run (default p1)
SET PROBLEM=%1
IF "%PROBLEM%"=="" SET PROBLEM=p1

ECHO.
ECHO ============================================================
ECHO   RTL-to-GDS Pipeline — %PROBLEM%
ECHO   Project: %PROJECT_DIR%
ECHO ============================================================
ECHO.

REM Check Docker is available
IF NOT EXIST %DOCKER% (
    ECHO ERROR: Docker not found at %DOCKER%
    ECHO Please install Docker Desktop for Windows.
    PAUSE
    EXIT /B 1
)

REM Check spec file exists
IF NOT EXIST "%PROJECT_DIR%\problems\%PROBLEM%.yaml" (
    ECHO ERROR: Spec file not found: problems\%PROBLEM%.yaml
    ECHO Available problems:
    DIR /B "%PROJECT_DIR%\problems\*.yaml" 2>NUL
    PAUSE
    EXIT /B 1
)

REM Check testbench exists
IF NOT EXIST "%PROJECT_DIR%\testbench\%PROBLEM%.v" (
    ECHO ERROR: Testbench not found: testbench\%PROBLEM%.v
    PAUSE
    EXIT /B 1
)

REM Check cells directory
IF NOT EXIST "%PROJECT_DIR%\skywater-pdk-libs-sky130_fd_sc_hd\cells" (
    ECHO ERROR: Sky130 cells not found.
    ECHO Expected: skywater-pdk-libs-sky130_fd_sc_hd\cells
    PAUSE
    EXIT /B 1
)

ECHO Running %PROBLEM% through full RTL-to-GDS flow...
ECHO.

%DOCKER% run -it ^
    -e DISPLAY=host.docker.internal:0.0 ^
    -v "%PROJECT_DIR%":/workspace ^
    %IMAGE% ^
    bash -c "cd /workspace && python3 agent.py --spec problems/%PROBLEM%.yaml --tb testbench/%PROBLEM%.v --cells skywater-pdk-libs-sky130_fd_sc_hd/cells --orfs /OpenROAD-flow-scripts/flow"

IF %ERRORLEVEL% EQU 0 (
    ECHO.
    ECHO ============================================================
    ECHO   Flow complete! Outputs saved to this folder:
    DIR /B "%PROJECT_DIR%\*.gds" 2>NUL
    DIR /B "%PROJECT_DIR%\*_pnr_report.txt" 2>NUL
    ECHO ============================================================
) ELSE (
    ECHO.
    ECHO Flow exited with code %ERRORLEVEL% — check output above.
)

ECHO.
PAUSE
