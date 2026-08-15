import argparse
import getpass
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from vm.iso import ISOManager, resolve_iso_path
from vm.preseed import PreseedServer
from vm.ssh import SSHProvisioner
from vm.virtualbox import VirtualBox


ROOT = Path(__file__).resolve().parent


# =====================================================================
# Configuration
# =====================================================================


def load_config() -> dict:
    config_path = ROOT / "config.yaml"

    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")

    return config


# =====================================================================
# Paths
# =====================================================================


def vm_base_path(cfg: dict) -> Path:
    username = getpass.getuser()

    return (
        Path(cfg["vm"]["goinfre_root"]).expanduser()
        / username
        / cfg["vm"]["disk_directory"]
    ).resolve()


def vm_disk_path(cfg: dict) -> Path:
    return (vm_base_path(cfg) / cfg["vm"]["disk_filename"]).resolve()


def ssh_private_key_path(cfg: dict) -> Path:
    return (ROOT / cfg["ssh"]["private_key"]).expanduser().resolve()


def ssh_public_key_path(cfg: dict) -> Path:
    return (ROOT / cfg["ssh"]["public_key"]).expanduser().resolve()


def generate_preseed(cfg: dict) -> Path:
    template_path = ROOT / "preseed" / "preseed.template.cfg"
    preseed_path = ROOT / "preseed" / "preseed.cfg"

    public_key = ssh_public_key_path(cfg).read_text(encoding="utf-8").strip()

    template = template_path.read_text(encoding="utf-8")

    preseed = template.replace(
        "__SSH_PUBLIC_KEY__",
        public_key,
    )

    preseed_path.write_text(
        preseed,
        encoding="utf-8",
    )

    return preseed_path


# =====================================================================
# SSH key management
# =====================================================================


def generate_ssh_keypair(cfg: dict) -> None:
    private_key = ssh_private_key_path(cfg)
    public_key = ssh_public_key_path(cfg)

    if private_key.exists() or public_key.exists():
        if private_key.exists() and public_key.exists():
            print("[*] SSH keypair already exists.")
            return

        raise RuntimeError(
            "SSH keypair is incomplete. Run 'python3 main.py clean' first."
        )

    private_key.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("[*] Generating SSH ED25519 keypair...")

    result = subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(private_key),
            "-C",
            cfg["vm"]["name"],
        ],
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError("ssh-keygen failed")


def remove_stale_ssh_host_key(
    cfg: dict,
) -> None:
    host = "127.0.0.1"
    port = cfg["network"]["ssh_host_port"]

    print(f"[*] Removing stale SSH host key for [{host}]:{port}...")

    result = subprocess.run(
        [
            "ssh-keygen",
            "-R",
            f"[{host}]:{port}",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        raise RuntimeError("Failed to remove stale SSH host key.")


# =====================================================================
# Create VM
# =====================================================================


def create_vm(cfg: dict) -> None:
    """
    Create and start the VM.

    IMPORTANT:
    This function NEVER destroys the VM automatically.

    If installation or SSH fails, the VM is intentionally preserved
    so that the user can inspect it.
    """

    name = cfg["vm"]["name"]

    remove_stale_ssh_host_key(cfg)

    vbox = VirtualBox(name)

    if vbox.exists():
        raise RuntimeError(
            f"VM '{name}' already exists.\n"
            f"Use:\n"
            f"    python3 main.py status\n"
            f"or destroy it explicitly with:\n"
            f"    python3 main.py destroy"
        )

    iso_path = resolve_iso_path(
        cfg["vm"]["goinfre_root"],
        cfg["debian"]["iso_filename"],
    )

    base_path = vm_base_path(cfg)
    disk = vm_disk_path(cfg)

    iso_manager = ISOManager(
        iso_path=iso_path,
        iso_url=cfg["debian"]["iso_url"],
        checksum_url=cfg["debian"]["checksum_url"],
    )

    iso_path = iso_manager.ensure()

    if not iso_path.is_file():
        raise FileNotFoundError(f"Debian ISO not found: {iso_path}")

    if disk.exists():
        raise RuntimeError(
            f"Virtual disk already exists: {disk}\nRun 'python3 main.py clean' first."
        )

    print(f"[*] VM name: {name}")
    print(f"[*] VM directory: {base_path}")
    print(f"[*] VM disk: {disk}")
    print(f"[*] Debian ISO: {iso_path}")

    # --------------------------------------------------------------
    # SSH keys
    # --------------------------------------------------------------

    generate_ssh_keypair(cfg)
    generate_preseed(cfg)

    private_key = ssh_private_key_path(cfg)
    public_key = ssh_public_key_path(cfg)

    print(f"[*] SSH private key: {private_key}")
    print(f"[*] SSH public key: {public_key}")

    preseed_server = None

    try:
        # ----------------------------------------------------------
        # VM creation
        # ----------------------------------------------------------

        print("[*] Creating VM...")

        base_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        vbox.create(
            base_folder=base_path,
        )

        # ----------------------------------------------------------
        # VM configuration
        # ----------------------------------------------------------

        print("[*] Configuring VM...")

        vbox.configure(
            cpus=cfg["vm"]["cpus"],
            memory_mb=cfg["vm"]["memory_mb"],
            ssh_port=cfg["network"]["ssh_host_port"],
        )

        # ----------------------------------------------------------
        # Storage
        # ----------------------------------------------------------

        print("[*] Creating storage controller...")

        vbox.create_storage_controller()

        print("[*] Creating virtual disk...")

        vbox.create_disk(
            disk,
            cfg["vm"]["disk_mb"],
        )

        print("[*] Attaching virtual disk...")

        vbox.attach_disk(disk)

        print("[*] Attaching Debian ISO...")

        vbox.attach_iso(iso_path)

        # ----------------------------------------------------------
        # Preseed HTTP server
        # ----------------------------------------------------------

        print("[*] Preparing Debian preseed...")

        preseed_server = PreseedServer(
            ROOT / "preseed",
            host="0.0.0.0",
            port=0,
        )

        preseed_server.start()

        preseed_url = f"http://10.0.2.2:{preseed_server.port}/preseed.cfg"

        print(f"[+] Preseed server listening on 0.0.0.0:{preseed_server.port}")

        print(f"[+] Preseed URL: {preseed_url}")

        # ----------------------------------------------------------
        # VirtualBox unattended installation
        # ----------------------------------------------------------

        print("[*] Configuring unattended Debian installation...")

        vbox.unattended_install(
            iso=iso_path,
            user=cfg["ssh"]["user"],
            password=cfg["installer"]["password"],
            full_user_name=cfg["installer"]["full_user_name"],
            hostname=f"{name}.local",
            preseed_url=preseed_url,
        )

        # ----------------------------------------------------------
        # Start VM
        # ----------------------------------------------------------

        print("[*] Starting VM...")

        vbox.start(headless=True)

        print("[*] Debian installer is running.")

        # ----------------------------------------------------------
        # SSH
        # ----------------------------------------------------------

        ssh = SSHProvisioner(
            user=cfg["ssh"]["user"],
            host="127.0.0.1",
            port=cfg["network"]["ssh_host_port"],
            private_key=private_key,
        )
        print("[*] Waiting for Debian installation and SSH...")

        ssh.wait_for_ssh(timeout=cfg["installer"]["timeout_seconds"])

        print("[+] Debian installation complete.")
        print("[+] SSH is available.")

        print()
        print("[+] VM creation successful.")
        print(
            f"[+] SSH: ssh -i {private_key} "
            f"-p {cfg['network']['ssh_host_port']} "
            f"{cfg['ssh']['user']}@127.0.0.1"
        )

    except KeyboardInterrupt:
        print()
        print("[!] Interrupted by user.")
        print("[!] VM has been preserved for debugging.")

        raise

    except Exception as exc:
        print()
        print("[ERROR] VM creation failed.")
        print(f"[ERROR] {exc}")
        print()
        print("[!] IMPORTANT: VM was NOT deleted.")
        print("[!] The VM has been preserved for debugging.")
        print()
        print("Useful commands:")
        print("    python3 main.py status")
        print(f"    VBoxManage showvminfo {name}")
        print(f"    VBoxManage startvm {name} --type gui")
        print("    python3 main.py destroy")

        raise

    finally:
        # ----------------------------------------------------------
        # The preseed server is only needed while the installer
        # is running. Once SSH is available, installation is done.
        # ----------------------------------------------------------

        if preseed_server is not None:
            print("[*] Stopping preseed server...")
            preseed_server.stop()


# =====================================================================
# Provision VM
# =====================================================================


def provision_vm(cfg: dict) -> None:
    name = cfg["vm"]["name"]

    vbox = VirtualBox(name)

    if not vbox.exists():
        raise RuntimeError(f"VM '{name}' does not exist.")

    private_key = ssh_private_key_path(cfg)

    if not private_key.is_file():
        raise FileNotFoundError(f"SSH private key not found: {private_key}")

    ssh = SSHProvisioner(
        user=cfg["ssh"]["user"],
        host="127.0.0.1",
        port=cfg["network"]["ssh_host_port"],
        private_key=private_key,
    )
    print("[*] Waiting for SSH...")

    ssh.wait_for_ssh(timeout=cfg["installer"]["timeout_seconds"])

    print("[+] SSH connection available.")

    print("[*] Running provisioning script...")

    ssh.run_script(ROOT / "scripts" / "provision.sh")

    print("[+] Provisioning complete.")


# =====================================================================
# Destroy VM
# =====================================================================


def destroy_vm(cfg: dict) -> None:
    name = cfg["vm"]["name"]

    vbox = VirtualBox(name)

    if not vbox.exists():
        print("[*] VM does not exist.")
        return

    print(f"[*] Destroying VM '{name}'...")

    vbox.delete()

    print("[+] VM destroyed.")


# =====================================================================
# Clean project resources
# =====================================================================


def cleanup(cfg: dict) -> None:
    """
    Explicit destructive cleanup.

    This function is ONLY called by:
        python3 main.py clean
        python3 main.py rebuild
    """

    print("[*] Cleaning project resources...")

    # --------------------------------------------------------------
    # VM
    # --------------------------------------------------------------

    vbox = VirtualBox(cfg["vm"]["name"])

    if vbox.exists():
        print(f"[*] Removing VM '{cfg['vm']['name']}'...")

        vbox.delete()

    else:
        print("[*] VM does not exist.")

    # --------------------------------------------------------------
    # VM directory
    # --------------------------------------------------------------

    vm_directory = vm_base_path(cfg)

    if vm_directory.exists():
        print(f"[*] Removing VM directory: {vm_directory}")

        shutil.rmtree(vm_directory)

        print(f"[+] Removed VM directory: {vm_directory}")

    # --------------------------------------------------------------
    # SSH keys
    # --------------------------------------------------------------

    private_key = ssh_private_key_path(cfg)
    public_key = ssh_public_key_path(cfg)

    for key in (
        private_key,
        public_key,
    ):
        if key.exists():
            print(f"[*] Removing SSH key: {key}")

            key.unlink()

    # --------------------------------------------------------------
    # Empty state directories
    # --------------------------------------------------------------

    state_ssh = private_key.parent

    if state_ssh.exists():
        try:
            state_ssh.rmdir()
        except OSError:
            pass

    state_directory = state_ssh.parent

    if state_directory.exists():
        try:
            state_directory.rmdir()
        except OSError:
            pass

    print("[+] Cleanup complete.")


# =====================================================================
# Rebuild
# =====================================================================


def rebuild_vm(cfg: dict) -> None:
    print("[*] Rebuilding VM...")

    # Explicitly destructive.
    cleanup(cfg)

    # Create does NOT clean up on failure.
    create_vm(cfg)

    # Provision separately.
    provision_vm(cfg)

    print("[+] Rebuild complete.")


# =====================================================================
# Status
# =====================================================================


def status_vm(cfg: dict) -> None:
    name = cfg["vm"]["name"]

    vbox = VirtualBox(name)

    print(f"VM: {name}")

    if not vbox.exists():
        print("State: not created")
    else:
        print(f"State: {vbox.state()}")

    print(f"VM directory: {vm_base_path(cfg)}")

    print(f"Disk: {vm_disk_path(cfg)}")

    print(f"SSH private key: {ssh_private_key_path(cfg)}")

    print(f"SSH public key: {ssh_public_key_path(cfg)}")


# =====================================================================
# CLI
# =====================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Debian VM manager")

    parser.add_argument(
        "command",
        choices=[
            "create",
            "provision",
            "destroy",
            "clean",
            "rebuild",
            "status",
        ],
        help="Operation to perform",
    )

    args = parser.parse_args()

    cfg = load_config()

    try:
        if args.command == "create":
            create_vm(cfg)

        elif args.command == "provision":
            provision_vm(cfg)

        elif args.command == "destroy":
            destroy_vm(cfg)

        elif args.command == "clean":
            cleanup(cfg)

        elif args.command == "rebuild":
            rebuild_vm(cfg)

        elif args.command == "status":
            status_vm(cfg)

    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
        sys.exit(130)

    except Exception as exc:
        print(
            f"\n[ERROR] {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


# =====================================================================
# Entry point
# =====================================================================

if __name__ == "__main__":
    main()
