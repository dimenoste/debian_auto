from pathlib import Path
import subprocess
import time


class VirtualBoxError(RuntimeError):
    """Raised when a VirtualBox operation fails."""


class VirtualBox:
    """Small wrapper around VBoxManage."""

    CONTROLLER = "SATA Controller"

    def __init__(self, name: str) -> None:
        self.name = name

    # ------------------------------------------------------------------
    # VBoxManage execution
    # ------------------------------------------------------------------

    def run(
        self,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        """Execute VBoxManage and raise on failure."""

        command = ["VBoxManage", *args]

        print("$", " ".join(command))

        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.stdout:
            print(result.stdout, end="")

        if result.stderr:
            print(result.stderr, end="")

        if result.returncode != 0:
            raise VirtualBoxError(
                f"VBoxManage failed with exit code "
                f"{result.returncode}"
            )

        return result

    # ------------------------------------------------------------------
    # VM inspection
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        """Return True if the VM is registered."""

        result = subprocess.run(
            [
                "VBoxManage",
                "showvminfo",
                self.name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        return result.returncode == 0

    def state(self) -> str:
        """Return the current VM state."""

        result = self.run(
            "showvminfo",
            self.name,
            "--machinereadable",
        )

        for line in result.stdout.splitlines():
            if line.startswith("VMState="):
                return line.split(
                    "=",
                    1,
                )[1].strip('"')

        raise VirtualBoxError(
            f"Unable to determine state of VM '{self.name}'"
        )

    # ------------------------------------------------------------------
    # VM creation
    # ------------------------------------------------------------------

    def create(
        self,
        base_folder: Path | None = None,
    ) -> None:
        """Create and register the VM."""

        if self.exists():
            raise VirtualBoxError(
                f"VM '{self.name}' already exists"
            )

        command = [
            "createvm",
            "--name",
            self.name,
            "--ostype",
            "Debian_64",
            "--register",
        ]

        if base_folder is not None:
            base_folder = base_folder.resolve()

            base_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            command.extend(
                [
                    "--basefolder",
                    str(base_folder),
                ]
            )

        self.run(*command)

    # ------------------------------------------------------------------
    # VM configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        cpus: int,
        memory_mb: int,
        ssh_port: int,
    ) -> None:
        """Configure CPU, memory, networking and boot order."""

        if cpus < 1:
            raise ValueError(
                "CPU count must be at least 1"
            )

        if memory_mb < 512:
            raise ValueError(
                "Memory must be at least 512 MB"
            )

        if not 1 <= ssh_port <= 65535:
            raise ValueError(
                f"Invalid SSH host port: {ssh_port}"
            )

        self.run(
            "modifyvm",
            self.name,
            "--memory",
            str(memory_mb),
            "--cpus",
            str(cpus),
            "--nic1",
            "nat",
            "--nat-localhostreachable1",
            "on",
            "--boot1",
            "dvd",
            "--boot2",
            "disk",
            "--boot3",
            "none",
            "--boot4",
            "none",
        )

        # Remove an existing SSH forwarding rule.
        subprocess.run(
            [
                "VBoxManage",
                "modifyvm",
                self.name,
                "--nat-pf1",
                "delete",
                "ssh",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        # Host:
        #   127.0.0.1:<ssh_port>
        #
        # Guest:
        #   :22
        #
        # Example:
        #   127.0.0.1:2222 -> VM:22

        self.run(
            "modifyvm",
            self.name,
            "--nat-pf1",
            f"ssh,tcp,127.0.0.1,{ssh_port},,22",
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def create_storage_controller(self) -> None:
        """Create the SATA controller."""

        self.run(
            "storagectl",
            self.name,
            "--name",
            self.CONTROLLER,
            "--add",
            "sata",
            "--controller",
            "IntelAhci",
        )

    def create_disk(
        self,
        path: Path,
        size_mb: int,
    ) -> None:
        """Create a VDI disk."""

        if size_mb < 4096:
            raise ValueError(
                "Virtual disk must be at least 4096 MB"
            )

        path = path.resolve()

        if path.exists():
            raise VirtualBoxError(
                f"Disk already exists: {path}"
            )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.run(
            "createmedium",
            "disk",
            "--filename",
            str(path),
            "--size",
            str(size_mb),
            "--format",
            "VDI",
        )

    def attach_disk(
        self,
        path: Path,
    ) -> None:
        """Attach the VDI to SATA port 0."""

        path = path.resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"Virtual disk not found: {path}"
            )

        self.run(
            "storageattach",
            self.name,
            "--storagectl",
            self.CONTROLLER,
            "--port",
            "0",
            "--device",
            "0",
            "--type",
            "hdd",
            "--medium",
            str(path),
        )

    def attach_iso(
        self,
        iso: Path,
    ) -> None:
        """Attach the Debian ISO to SATA port 1."""

        iso = iso.resolve()

        if not iso.is_file():
            raise FileNotFoundError(
                f"Debian ISO not found: {iso}"
            )

        self.run(
            "storageattach",
            self.name,
            "--storagectl",
            self.CONTROLLER,
            "--port",
            "1",
            "--device",
            "0",
            "--type",
            "dvddrive",
            "--medium",
            str(iso),
        )

    # ------------------------------------------------------------------
    # Unattended installation
    # ------------------------------------------------------------------

    def unattended_install(
        self,
        iso: Path,
        user: str,
        password: str,
        full_user_name: str,
        hostname: str,
        preseed_url: str,
    ) -> None:
        """
        Configure VirtualBox unattended installation.

        The preseed URL is passed to the Debian installer through
        VirtualBox's extra kernel parameters.
        """

        iso = iso.resolve()

        if not iso.is_file():
            raise FileNotFoundError(
                f"Debian ISO not found: {iso}"
            )

        if not user:
            raise ValueError(
                "Guest username cannot be empty"
            )

        if not password:
            raise ValueError(
                "Guest password cannot be empty"
            )

        if not full_user_name:
            raise ValueError(
                "Full user name cannot be empty"
            )

        if not hostname:
            raise ValueError(
                "Hostname cannot be empty"
            )

        if not preseed_url:
            raise ValueError(
                "Preseed URL cannot be empty"
            )

        kernel_parameters = (
            "auto=true "
            "priority=critical "
            f"preseed/url={preseed_url}"
        )
        self.run(
            "unattended",
            "install",
            self.name,
            "--iso",
            str(iso),
            "--user",
            user,
            "--user-password",
            password,
            "--full-user-name",
            full_user_name,
            "--hostname",
            hostname,
            "--locale",
            "en_US",
            "--time-zone",
            "UTC",
            "--no-install-additions",
            "--extra-install-kernel-parameters",
            kernel_parameters,
        )

    # ------------------------------------------------------------------
    # VM lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        headless: bool = True,
    ) -> None:
        """Start the VM."""

        frontend = (
            "headless"
            if headless
            else "gui"
        )

        self.run(
            "startvm",
            self.name,
            "--type",
            frontend,
        )

    def wait_for_poweroff(
        self,
        timeout: int = 30,
    ) -> None:
        """Wait until the VM reaches poweroff."""

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if not self.exists():
                return

            try:
                current_state = self.state()
            except VirtualBoxError:
                time.sleep(1)
                continue

            if current_state == "poweroff":
                return

            time.sleep(1)

        raise VirtualBoxError(
            f"VM '{self.name}' did not power off "
            f"within {timeout} seconds"
        )

    def stop(self) -> None:
        """Force the VM into the poweroff state."""

        if not self.exists():
            return

        current_state = self.state()

        if current_state == "poweroff":
            return

        if current_state not in {
            "running",
            "paused",
        }:
            raise VirtualBoxError(
                f"Cannot stop VM '{self.name}' "
                f"while it is in state "
                f"'{current_state}'"
            )

        print(
            f"[*] Powering off VM '{self.name}'..."
        )

        self.run(
            "controlvm",
            self.name,
            "poweroff",
        )

        self.wait_for_poweroff()

    def delete(self) -> None:
        """Power off, unregister and delete the VM."""

        if not self.exists():
            return

        current_state = self.state()

        if current_state != "poweroff":
            self.stop()

        print(
            f"[*] Unregistering VM '{self.name}'..."
        )

        self.run(
            "unregistervm",
            self.name,
            "--delete",
        )