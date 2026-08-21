from pathlib import Path
import re
import shlex
import subprocess
import time


class SSHProvisioner:
    def __init__(
        self,
        user: str,
        host: str,
        port: int,
        private_key: Path,
    ):
        self.user = user
        self.host = host
        self.port = port
        self.private_key = Path(private_key)

    def command(self, *remote_command: str) -> list[str]:
        return [
            "ssh",
            "-i",
            str(self.private_key),
            "-p",
            str(self.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=3",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{self.user}@{self.host}",
            *remote_command,
        ]

    def wait_for_ssh(self, timeout: int) -> None:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            result = subprocess.run(
                self.command("true"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

            if result.returncode == 0:
                print("[+] SSH key authentication succeeded.")
                return

            time.sleep(5)

        raise TimeoutError(f"SSH did not become available within {timeout} seconds.")

    def run(
        self,
        command: str,
    ) -> None:
        print(f"[*] Remote: {command}")

        subprocess.run(
            self.command(
                "bash",
                "-lc",
                command,
            ),
            check=True,
        )

    # def run_script(
    #     self,
    #     script: Path,
    # ) -> None:
    #     script = script.resolve()

    #     if not script.is_file():
    #         raise FileNotFoundError(f"Provisioning script not found: {script}")

    #     print(f"[*] Provisioning with {script}")

    #     with script.open("rb") as f:
    #         subprocess.run(
    #             self.command("bash", "-s"),
    #             stdin=f,
    #             check=True,
    #         )

    def run_script(
        self,
        script: Path,
        environment: dict[str, str] | None = None,
    ) -> None:
        script = script.resolve()

        if not script.is_file():
            raise FileNotFoundError(f"Provisioning script not found: {script}")

        print(f"[*] Provisioning with {script}")

        prefix = ""

        if environment:
            for key in environment:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    raise ValueError(f"Invalid environment variable name: {key}")

            prefix = "".join(
                f"export {key}={shlex.quote(value)}\n"
                for key, value in environment.items()
            )

        script_data = script.read_bytes()

        subprocess.run(
            self.command("bash", "-s"),
            input=prefix.encode() + script_data,
            check=True,
        )
