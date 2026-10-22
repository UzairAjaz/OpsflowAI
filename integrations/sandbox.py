from __future__ import annotations

import shutil
import subprocess
import time
from typing import Protocol

from pydantic import BaseModel

from app.config import settings

class CommandResult(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0

class SandboxRunner(Protocol):
    name: str

    def run(self, argv: list[str], *, timeout: int | None = None) -> CommandResult: ...

class LocalSandbox:
    name = "local"

    def run(self, argv: list[str], *, timeout: int | None = None) -> CommandResult:
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, shell=False
            )
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 124, "", "timeout"
        except FileNotFoundError as exc:
            code, out, err = 127, "", str(exc)
        return CommandResult(
            command=argv,
            exit_code=code,
            stdout=out[-4000:],
            stderr=err[-4000:],
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

class DockerSandbox:
    name = "docker"

    def __init__(
        self,
        image: str,
        timeout: int = 30,
        memory: str = "256m",
        cpus: str = "0.5",
        network: bool = False,
    ) -> None:
        self._image = image
        self._timeout = timeout
        self._memory = memory
        self._cpus = cpus
        self._network = network

    def run(self, argv: list[str], *, timeout: int | None = None) -> CommandResult:
        timeout = timeout or self._timeout
        docker = shutil.which("docker")
        if not docker:
            return CommandResult(command=argv, exit_code=127, stderr="docker not found")

        cmd = [
            docker,
            "run",
            "--rm",
            "--pids-limit",
            "256",
            "--memory",
            self._memory,
            "--cpus",
            self._cpus,
        ]
        if not self._network:
            cmd += ["--network", "none"]
        cmd += [self._image, *argv]

        start = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 124, "", "timeout"
        return CommandResult(
            command=argv,
            exit_code=code,
            stdout=out[-4000:],
            stderr=err[-4000:],
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

class FakeSandbox:
    name = "fake"

    def __init__(self, exit_codes: dict[str, int] | None = None, default_exit: int = 0) -> None:
        self._exit_codes = exit_codes or {}
        self._default = default_exit

    def run(self, argv: list[str], *, timeout: int | None = None) -> CommandResult:
        code = self._exit_codes.get(argv[0], self._default) if argv else self._default
        return CommandResult(command=argv, exit_code=code, stdout=f"[fake] {' '.join(argv)}")

_OVERRIDE: SandboxRunner | None = None

def set_sandbox(runner: SandboxRunner | None) -> None:
    global _OVERRIDE
    _OVERRIDE = runner

def get_sandbox() -> SandboxRunner:
    if _OVERRIDE is not None:
        return _OVERRIDE
    backend = settings.sandbox_backend
    if backend == "local":
        return LocalSandbox()
    if backend == "fake":
        return FakeSandbox()
    return DockerSandbox(
        image=settings.sandbox_image,
        timeout=settings.sandbox_timeout_seconds,
        memory=settings.sandbox_memory_limit,
        cpus=settings.sandbox_cpus,
        network=settings.sandbox_network,
    )
