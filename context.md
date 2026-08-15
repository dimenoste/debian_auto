# Debian VM Automation Project — Full Handoff Context

This document is the authoritative blueprint for the current state of the project. It is intended to allow another LLM or developer to understand the architecture, reproduce the project, diagnose failures, and extend it without reintroducing previously fixed problems.

---

## 1. Project purpose

The project automates the creation of a small Debian development VM using VirtualBox.

The primary motivation is the environment at **42**:

* School machines have relatively limited local storage.
* `/goinfre` provides substantially more storage.
* `/goinfre` is tied to the physical machine being used.
* Moving to another 42 machine therefore means either:

  * reconnecting to the machine containing the VM, or
  * recreating the VM on the new machine.
* A disposable VM that can be recreated automatically is therefore much more practical than maintaining a manually configured VM.

The project reduces the recreation process to essentially:

```text
uv run python main.py rebuild
```

The VM is then:

1. Created on `/goinfre`.
2. Given the configured CPU/RAM/storage resources.
3. Installed from a Debian netinst ISO.
4. Configured as a minimal CLI system.
5. Given `sudo`.
6. Given `openssh-server`.
7. Configured for SSH key authentication.
8. Accessible from the host through localhost port forwarding.
9. Provisioned through `scripts/provision.sh`.
10. Suitable for development through VS Code Remote SSH.

The VM is deliberately disposable. The host project contains the automation needed to recreate it rather than treating the VM itself as precious state.

---

# 2. Current project architecture

Current conceptual structure:

```text
debian-automation/
├── config.yaml
├── main.py
├── requirements.txt
├── preseed/
│   ├── preseed.cfg
│   └── potentially preseed.cfg.template
├── scripts/
│   └── provision.sh
├── state/
│   └── ssh/
│       ├── debian-vm_ed25519
│       └── debian-vm_ed25519.pub
└── vm/
    ├── __init__.py
    ├── iso.py
    ├── preseed.py
    ├── ssh.py
    └── virtualbox.py
```

`__pycache__` directories are irrelevant generated files.

The project intentionally avoids introducing additional third-party dependencies.

The Python standard library is used for:

* ISO downloads
* SHA-512 verification
* HTTP preseed serving
* threading
* socket handling
* subprocess execution
* filesystem operations

Existing project dependencies such as `PyYAML` remain unchanged.

---

# 3. Current execution model

The main lifecycle is:

```text
main.py
   |
   +-- load config.yaml
   |
   +-- ISOManager
   |      |
   |      +-- check ISO
   |      +-- download if missing
   |      +-- verify SHA-512
   |
   +-- generate SSH keypair
   |
   +-- generate/render preseed
   |
   +-- VirtualBox
   |      |
   |      +-- create VM
   |      +-- configure CPU/RAM/network
   |      +-- create disk
   |      +-- attach ISO
   |
   +-- PreseedServer
   |      |
   |      +-- dynamically allocate host port
   |      +-- serve preseed.cfg
   |
   +-- VBoxManage unattended installation
   |
   +-- start VM
   |
   +-- wait for SSH
   |
   +-- stop preseed server
   |
   +-- provision.sh through SSH
```

The important separation is:

```text
ISO management
VirtualBox management
Debian installation configuration
SSH management
Post-install provisioning
```

Each layer should remain independent.

---

# 4. Important current change: ISO management

The project now handles the case where the user does **not** already have the Debian ISO.

Previously `main.py` did:

```python
if not iso_path.is_file():
    raise FileNotFoundError(...)
```

This made the project unusable on a new 42 machine unless the ISO had already been manually copied into `/goinfre`.

The current design instead uses `vm/iso.py`.

The important behavior is:

```text
ISO exists
    |
    +-- verify SHA-512
    |
    +-- valid -> continue
    |
    +-- invalid -> delete and redownload

ISO does not exist
    |
    +-- download Debian ISO
    +-- download SHA512SUMS
    +-- verify downloaded ISO
    +-- move verified ISO into final location
```

The ISO therefore becomes an automatically managed dependency.

---

# 5. Current ISOManager

The current implementation is conceptually:

```python
from __future__ import annotations

import getpass
import hashlib
import urllib.request
from pathlib import Path


def resolve_iso_path(goinfre_root: str, iso_filename: str) -> Path:
    return Path(goinfre_root) / getpass.getuser() / iso_filename


class ISOError(RuntimeError):
    pass


class ISOManager:
    def __init__(
        self,
        iso_path: Path,
        iso_url: str,
        checksum_url: str,
    ):
        self.iso_path = iso_path
        self.iso_url = iso_url
        self.checksum_url = checksum_url

    def _download(self, url: str, destination: Path) -> None:
        ...
    
    def _download_checksum_manifest(self) -> str:
        ...
    
    def _expected_sha512(self) -> str:
        ...
    
    def _sha512(self, path: Path) -> str:
        ...
    
    def verify(self) -> bool:
        ...
    
    def ensure(self) -> Path:
        ...
```

The implementation uses only Python's standard library.

The download is streamed in chunks rather than loading the ISO into memory.

The checksum is calculated incrementally using:

```python
hashlib.sha512()
```

---

# 6. Current ISO location

The current ISO is:

```text
/goinfre/mberraho/debian-13.6.0-amd64-netinst.iso
```

The path is generated using:

```python
resolve_iso_path(
    cfg["vm"]["goinfre_root"],
    cfg["debian"]["iso_filename"],
)
```

The intended general form is:

```text
<goinfre_root>/<username>/<iso_filename>
```

For example:

```text
/goinfre/mberraho/debian-13.6.0-amd64-netinst.iso
```

This means the ISO is also kept on `/goinfre`, rather than consuming valuable space in the project directory.

---

# 7. Current ISO verification

The project verifies the ISO against Debian's official SHA-512 manifest.

Current manifest:

```text
https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA512SUMS
```

The verification flow is:

```text
download/read SHA512SUMS
        |
        v
find exact ISO filename
        |
        v
calculate local SHA-512
        |
        v
compare
```

A successful run produces:

```text
[*] Debian ISO found: /goinfre/mberraho/debian-13.6.0-amd64-netinst.iso
[*] Checking SHA-512: /goinfre/mberraho/debian-13.6.0-amd64-netinst.iso
[*] Downloading checksum manifest: https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA512SUMS
[+] ISO SHA-512: OK
```

The ISO must never be attached to the VM before verification succeeds.

---

# 8. ISO download behavior

If the ISO does not exist:

```text
[*] Debian ISO not found: ...
[*] Downloading: <Debian ISO URL>
[*] Destination: <path>.part
```

The download first goes to:

```text
<iso>.iso.part
```

Only after checksum verification does it become:

```text
<iso>.iso
```

This prevents a partially downloaded ISO from being mistaken for a valid ISO.

If the checksum fails, the `.part` file is removed.

This is important because a machine can lose network connectivity or `/goinfre` space during a large ISO download.

---

# 9. Current Debian ISO

The project uses the Debian 13.6.0 amd64 netinst ISO:

```text
debian-13.6.0-amd64-netinst.iso
```

The exact URL is configuration-driven rather than hardcoded throughout the application.

The project should continue using Debian's official distribution infrastructure.

---

# 10. VM storage location

The VM lives on `/goinfre`.

Current base:

```text
/goinfre/mberraho/debian-vm
```

Current disk:

```text
/goinfre/mberraho/debian-vm/debian-dev.vdi
```

The actual VirtualBox machine directory is:

```text
/goinfre/mberraho/debian-vm/debian-dev/
```

This is deliberate.

The project directory remains small and portable, while:

* ISO
* VM configuration
* VDI

are stored on `/goinfre`.

---

# 11. Default VM resources

The VM resources are configurable through `config.yaml`.

The default disk is approximately:

```text
9.8 GB
```

Inside the VM, the expected partitioning is approximately:

```text
NAME   MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
sda      8:0    0   9.8G  0 disk
sda1     8:1    0   9.2G  0 part /
sda2     8:2    0     1K  0 part
sda5     8:5    0   572M  0 part [SWAP]
sr0     11:0    1  1024M  1 rom
```

The RAM/CPU configuration is controlled through:

```yaml
vm:
    cpus: ...
    memory_mb: ...
    disk_mb: ...
```

The user is expected to modify those values according to the host machine.

The important architectural rule is:

```text
Do not hard-code VM resources in Python.
```

Changing:

```yaml
cpus:
memory_mb:
disk_mb:
```

should be sufficient to change the VM specifications.

---

# 12. Why configurable VM resources matter at 42

Different 42 machines have different local resource constraints.

The project is specifically designed around the idea that:

```text
local machine resources
        +
large /goinfre storage
        =
cheap disposable development VM
```

The VM should therefore not assume a powerful host.

A user can reduce:

```text
CPU
RAM
disk
```

when working on a constrained machine.

Conversely, a machine with more resources can increase them.

---

# 13. VM networking

The VM uses VirtualBox NAT networking.

Conceptually:

```text
Host
127.0.0.1:2222
       |
       | VirtualBox NAT port forwarding
       v
Guest
10.0.2.x:22
       |
       v
sshd
```

The host connects to:

```text
127.0.0.1:2222
```

The guest's SSH server listens on:

```text
22
```

VirtualBox forwards:

```text
127.0.0.1:2222 -> guest:22
```

The VM does not expose SSH directly on the LAN.

---

# 14. Security implications of the network design

The VM should not be described simply as being on a "private network."

The more precise description is:

```text
VirtualBox NAT + host-loopback SSH forwarding
```

The SSH endpoint is:

```text
127.0.0.1:2222
```

This means the service is intended to be reachable from the host itself, not directly from other machines on the network.

That is significantly safer than forwarding:

```text
0.0.0.0:2222 -> guest:22
```

because the latter would potentially expose SSH to the local network.

The intended configuration is therefore:

```text
127.0.0.1:2222
```

not:

```text
0.0.0.0:2222
```

The VM itself still has its own network connectivity through NAT for things such as:

```text
apt
curl
git
```

but inbound SSH is restricted to the host's loopback interface.

---

# 15. SSH configuration

Guest user:

```text
dev
```

Host:

```text
127.0.0.1
```

Host port:

```text
2222
```

Guest port:

```text
22
```

Manual connection:

```bash
ssh -p 2222 dev@127.0.0.1
```

The project-generated private key is:

```text
state/ssh/debian-vm_ed25519
```

Public key:

```text
state/ssh/debian-vm_ed25519.pub
```

The normal automated connection is therefore:

```bash
ssh \
    -i state/ssh/debian-vm_ed25519 \
    -p 2222 \
    dev@127.0.0.1
```

---

# 16. Is SSH passwordless?

The intended final configuration is **key-based SSH authentication**.

The project generates an ED25519 keypair:

```text
debian-vm_ed25519
debian-vm_ed25519.pub
```

The public key is installed into the VM for:

```text
dev
```

The private key remains on the host.

Therefore normal SSH usage does not require typing the Debian user's password.

This should not be confused with:

```text
no authentication
```

Authentication still occurs through the private SSH key.

The Debian installer password exists primarily to bootstrap the account/install process.

The desired end state is:

```text
host private key
       |
       v
SSH authentication
       |
       v
dev@debian-vm
```

not:

```text
username + password on every SSH connection
```

---

# 17. SSH host-key handling

Every recreated VM can generate a new SSH host key.

Because the VM is disposable, the same endpoint:

```text
[127.0.0.1]:2222
```

may legitimately represent a completely new VM after:

```bash
python3 main.py rebuild
```

Therefore normal SSH known-host verification would produce:

```text
WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!
```

The automation handles this explicitly.

The SSH client commands should use:

```text
-o StrictHostKeyChecking=no
-o UserKnownHostsFile=/dev/null
```

These options affect only the **host-side SSH client**.

They do not weaken the guest's SSH authentication mechanism.

They simply tell the disposable VM automation:

```text
do not persistently trust the previous VM's host key
```

This is appropriate for a disposable local development VM.

---

# 18. Important distinction about SSH security

These options:

```text
StrictHostKeyChecking=no
UserKnownHostsFile=/dev/null
```

do not mean:

```text
SSH is unauthenticated.
```

They mean:

```text
the host does not persistently verify the server identity using ~/.ssh/known_hosts
```

Authentication of the user should still use:

```text
ED25519 private key
```

The security model is therefore:

```text
Network exposure:
    localhost only

User authentication:
    SSH key

Server identity:
    deliberately not persisted because VM is disposable
```

This is suitable for the project's local disposable-VM use case, but it would not be the correct configuration for a production server.

---

# 19. SSHProvisioner responsibilities

`vm/ssh.py` owns SSH behavior.

It should contain one common command builder.

Conceptually:

```python
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
```

Every SSH operation should use this builder.

Do not duplicate SSH options in:

```text
main.py
provision_vm()
wait_for_ssh()
run_script()
```

---

# 20. SSH readiness

Starting the VM does not mean SSH is immediately available.

The actual sequence is:

```text
VirtualBox starts VM
        |
        v
Debian boots
        |
        v
installer finishes
        |
        v
system reboots
        |
        v
systemd starts ssh.service
        |
        v
port 22 accepts connections
        |
        v
SSHProvisioner succeeds
```

Therefore:

```python
vbox.start(headless=True)
```

must be followed by:

```python
ssh.wait_for_ssh(...)
```

The project must not assume that the VM is ready immediately after `start()`.

---

# 21. Previous SSH failure

A previous manual connection produced:

```text
kex_exchange_identification: read: Connection reset by peer
Connection reset by 127.0.0.1 port 2222
```

This was not a host-key problem.

It indicated that the forwarding path existed but the guest SSH service was not yet usable.

Likely causes included:

```text
Debian installer still running
openssh-server not installed
sshd not running
preseed not applied
VM not yet booted into installed system
```

The correct fix is therefore to make Debian's installation reliably install and start:

```text
openssh-server
```

and then wait for SSH.

---

# 22. Debian installation strategy

The project uses:

```text
Debian netinst ISO
+
VirtualBox unattended installation
+
Debian preseed
```

It does **not** build a custom ISO.

It does **not** require a separate PXE/netboot infrastructure.

The high-level process is:

```text
Debian ISO
    |
    v
VirtualBox unattended installation
    |
    +-- Debian kernel parameters
            |
            +-- auto=true
            +-- priority=critical
            +-- preseed/url=<temporary HTTP URL>
    |
    v
Debian installer
    |
    v
preseed.cfg
```

---

# 23. Why preseed is necessary

VirtualBox's:

```text
VBoxManage unattended install
```

is useful for configuring an unattended installation, but it does not provide sufficiently precise Debian package-selection control for this project.

An earlier attempt used:

```text
--package-selection-adjustment minimal openssh-server
```

This was incorrect.

The option:

```text
--package-selection-adjustment
```

expects a value such as:

```text
minimal
```

not a list of Debian packages.

Even with:

```text
--package-selection-adjustment minimal
```

the installation did not reliably guarantee the required:

```text
openssh-server
```

package.

Therefore Debian's own installer configuration is used for package selection.

---

# 24. Desired Debian installation

The VM should be:

```text
CLI only
minimal
development oriented
SSH enabled
sudo enabled
```

It should not install a desktop environment.

Specifically, it should avoid unnecessary packages/tasks such as:

```text
GNOME
KDE
XFCE
Firefox
LibreOffice
other desktop applications
```

The previous installation approach resulted in unnecessary desktop software, which is undesirable on a small VM.

---

# 25. Preseed package requirements

At minimum, the installation needs:

```text
openssh-server
sudo
```

Other basic utilities can be included where justified.

Typical development packages can instead be installed later by:

```text
scripts/provision.sh
```

This creates a clean separation:

```text
preseed
    =
minimum system required to boot and access the VM

provision.sh
    =
development environment
```

---

# 26. `scripts/provision.sh`

The provisioning script is the correct place for additional development dependencies.

For example:

```text
git
curl
wget
build-essential
gcc
g++
make
python3
python3-pip
python3-venv
clang
gdb
strace
ripgrep
tmux
vim/neovim
pkg-config
```

The exact list should remain project-specific.

The user can add additional dependencies to:

```text
scripts/provision.sh
```

without modifying the VM creation mechanism.

This is particularly useful for 42 projects because the base VM can remain small while the development environment can evolve.

---

# 27. Temporary preseed HTTP server

The project uses a small Python HTTP server.

It should use only the standard library:

```python
http.server
socketserver
threading
socket
```

No Flask.

No FastAPI.

No external HTTP server.

The server's sole responsibility is:

```text
serve preseed.cfg
```

during Debian installation.

Once the installed VM is reachable through SSH, the HTTP server can be shut down.

---

# 28. Dynamic HTTP port

A previous implementation used:

```text
8080
```

and failed:

```text
[Errno 98] Address already in use
```

Therefore the server must not assume that 8080 is available.

Preferred implementation:

```python
port=0
```

When a server binds to port `0`, the operating system chooses a free ephemeral port.

The implementation must then expose:

```python
server.port
```

so `main.py` can construct the actual URL.

Conceptually:

```text
0.0.0.0:0
      |
      v
OS chooses 49152
      |
      v
0.0.0.0:49152
```

---

# 29. Preseed server interface

`vm/preseed.py` should provide approximately:

```python
class PreseedServer:
    def __init__(
        self,
        directory: Path,
        host: str = "0.0.0.0",
        port: int = 0,
        guest_host: str = "10.0.2.2",
    ):
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    @property
    def port(self) -> int:
        ...

    def url(self, filename: str) -> str:
        ...
```

The implementation must:

* create the server
* bind the requested host
* support dynamic ports
* run in a background thread
* expose the selected port
* serve only the intended directory
* shut down cleanly
* not require external dependencies

---

# 30. Important NAT/preseed networking detail

The Debian installer runs **inside the VM**.

Therefore:

```text
127.0.0.1
```

from the Debian installer refers to:

```text
the Debian VM itself
```

It does not refer to the host.

Therefore this is incorrect:

```text
preseed/url=http://127.0.0.1:<port>/preseed.cfg
```

The intended VirtualBox NAT host address is:

```text
10.0.2.2
```

Therefore the server should bind:

```text
0.0.0.0:<dynamic-port>
```

and the Debian installer should receive:

```text
http://10.0.2.2:<dynamic-port>/preseed.cfg
```

This assumption should be tested on the target VirtualBox environment.

---

# 31. Preseed URL lifecycle

The server must remain alive throughout the part of installation that requires it.

Correct sequence:

```text
start PreseedServer
        |
        v
obtain selected port
        |
        v
construct preseed URL
        |
        v
configure VBox unattended install
        |
        v
start VM
        |
        v
Debian installer downloads preseed
        |
        v
installation completes
        |
        v
SSH becomes available
        |
        v
stop PreseedServer
```

Incorrect:

```text
start server
configure VBox
stop server
start VM
```

because the Debian installer would no longer be able to retrieve the preseed.

---

# 32. VirtualBox unattended installation

`vm/virtualbox.py` should expose something similar to:

```python
def unattended_install(
    self,
    iso: Path,
    user: str,
    password: str,
    full_user_name: str,
    hostname: str,
    preseed_url: str,
) -> None:
    ...
```

The generated `VBoxManage` command should include the relevant unattended-install options:

```text
--iso
--user
--user-password
--full-user-name
--hostname
--locale
--time-zone
--no-install-additions
--extra-install-kernel-parameters
```

The kernel parameters should conceptually contain:

```text
auto=true
priority=critical
preseed/url=http://10.0.2.2:<port>/preseed.cfg
```

They must be passed to `VBoxManage` as the appropriate single argument.

---

# 33. Important unattended-install semantic

This command:

```text
VBoxManage unattended install ...
```

does not mean:

```text
Debian installation is finished
```

It configures the unattended installation.

The actual installation occurs after the VM is started.

Therefore:

```python
vbox.unattended_install(...)
```

must be followed by:

```python
vbox.start(...)
```

and then:

```python
ssh.wait_for_ssh(...)
```

---

# 34. VM creation lifecycle

`create_vm()` should conceptually perform:

```text
1. Check VM does not already exist.
2. Ensure ISO exists and is verified.
3. Ensure SSH keypair exists.
4. Generate/render preseed.
5. Create VM.
6. Configure VM.
7. Create storage controller.
8. Create virtual disk.
9. Attach disk.
10. Attach ISO.
11. Start preseed HTTP server.
12. Configure unattended Debian installation.
13. Start VM.
14. Wait for SSH.
15. Stop preseed server.
16. Report success.
```

The preseed server must be cleaned up in `finally`.

---

# 35. Do not start the VM twice

A previous implementation accidentally performed:

```text
vbox.start()
```

inside one part of `create_vm()` and then started the VM again later.

This must not happen.

There should be exactly one:

```python
vbox.start(headless=True)
```

per creation attempt.

---

# 36. VM failure policy

`create_vm()` deliberately does **not** automatically destroy the VM on failure.

This is important for debugging.

If installation fails, the VM should remain available so the user can inspect it:

```bash
python3 main.py status
```

```bash
VBoxManage showvminfo debian-dev
```

```bash
VBoxManage startvm debian-dev --type gui
```

```bash
python3 main.py destroy
```

The application should therefore distinguish:

```text
automatic cleanup
```

from:

```text
explicit destructive cleanup
```

---

# 37. `rebuild`

`rebuild` is intentionally destructive.

Its intended sequence is:

```python
cleanup(cfg)
create_vm(cfg)
provision_vm(cfg)
```

Therefore:

```bash
uv run python main.py rebuild
```

means:

```text
delete existing VM/state
ensure ISO
create a fresh VM
install Debian
configure SSH
run provisioning
```

This is the main "move to another 42 machine and recreate everything" workflow.

---

# 38. `create`

The intended command:

```bash
uv run python main.py create
```

creates the VM but should not unnecessarily destroy an existing VM.

If the VM already exists, it should fail with a useful message:

```text
VM 'debian-dev' already exists.
Use:
    python3 main.py status
or destroy it explicitly with:
    python3 main.py destroy
```

---

# 39. `provision`

The intended command:

```bash
uv run python main.py provision
```

assumes the VM already exists.

It:

1. checks the VM
2. checks the SSH private key
3. waits for SSH
4. executes:

```text
scripts/provision.sh
```

inside the VM.

Provisioning is deliberately separated from VM creation.

---

# 40. `destroy`

The intended command:

```bash
uv run python main.py destroy
```

deletes the VirtualBox VM.

It should not silently destroy unrelated files.

---

# 41. `clean`

`clean` is explicit destructive project cleanup.

It is intended to remove:

```text
VM
VM storage
leftover VDI
generated SSH keys
empty state directories
```

It should not recursively delete arbitrary `/goinfre` content.

In particular, do not replace the cleanup with:

```python
shutil.rmtree(vm_directory)
```

without carefully constraining the target.

---

# 42. Previous cleanup bug

A previous `rebuild` produced:

```text
[*] VM does not exist.
```

but VirtualBox still had:

```text
/goinfre/mberraho/debian-vm/debian-dev/debian-dev.vbox
```

Then creation failed:

```text
VBoxManage: error: Machine settings file
'/goinfre/mberraho/debian-vm/debian-dev/debian-dev.vbox'
already exists
```

This demonstrates an important distinction:

```text
VirtualBox registry state
```

and:

```text
filesystem state
```

are not necessarily identical.

A VM can be unregistered while its directory still exists.

Therefore `cleanup()` must handle stale filesystem state.

---

# 43. Correct cleanup principle

The cleanup logic should verify:

```text
Is VM registered?
```

and independently:

```text
Does VM directory exist?
```

and:

```text
Does VDI exist?
```

If the VM is not registered but the expected VM directory is stale, it is safe to remove that **known project-owned VM directory** during explicit:

```text
clean
rebuild
```

provided the path is derived from the configured VM base directory and VM name.

This is the specific reason the earlier cleanup implementation failed.

---

# 44. Recommended cleanup sequence

Conceptually:

```text
1. Check whether VirtualBox knows the VM.
2. If registered:
       unregistervm --delete
3. Verify the VM is no longer registered.
4. If the expected VM directory still exists:
       remove the stale project-owned VM directory.
5. If the configured VDI still exists:
       remove it if it is no longer owned by a registered VM.
6. Remove generated SSH keys.
7. Remove empty state directories.
```

The cleanup must remain explicit and deterministic.

---

# 45. VirtualBox delete exit-code behavior

A previous `unregistervm --delete` operation successfully removed the VM but returned:

```text
exit code 2
```

Therefore `VirtualBox.delete()` should not blindly assume:

```text
non-zero = deletion failed
```

A robust implementation should:

```text
run unregistervm --delete
        |
        +-- return code 0
        |      -> success
        |
        +-- non-zero
               |
               +-- check whether VM still exists
                       |
                       +-- does not exist -> treat as success
                       |
                       +-- still exists -> raise error
```

The cleanup output should not print:

```text
[+] Cleanup complete.
```

multiple times.

---

# 46. Current `cleanup()` issue

The previous beginning of the function was:

```python
def cleanup(cfg: dict) -> None:
    print("[*] Cleaning project resources...")

    vbox = VirtualBox(
        cfg["vm"]["name"]
    )

    if vbox.exists():
        print(
            f"[*] Removing VM "
            f"'{cfg['vm']['name']}'..."
        )

        vbox.delete()

    else:
        print("[*] VM does not exist.")

    disk = vm_disk_path(cfg)

    if disk.exists():
        print(
            f"[*] Removing virtual disk: {disk}"
        )

        disk.unlink()

    vm_directory = disk.parent

    if vm_directory.exists():
        try:
            vm_directory.rmdir()
        except OSError:
            pass
```

The problem is that:

```text
vm_directory
```

is:

```text
/goinfre/mberraho/debian-vm
```

while VirtualBox actually created:

```text
/goinfre/mberraho/debian-vm/debian-dev/
```

The stale `.vbox` file therefore survived.

Cleanup needs to distinguish:

```text
base folder:
    /goinfre/.../debian-vm

VM directory:
    /goinfre/.../debian-vm/debian-dev
```

The latter is the directory responsible for the observed creation failure.

---

# 47. SSH key generation

The project owns:

```text
state/ssh/debian-vm_ed25519
state/ssh/debian-vm_ed25519.pub
```

They should be generated automatically.

Conceptually:

```bash
ssh-keygen \
    -t ed25519 \
    -N "" \
    -f state/ssh/debian-vm_ed25519 \
    -C debian-dev
```

The key must not be regenerated on every `create`.

Expected behavior:

```text
private + public key exist
    -> reuse

neither exists
    -> generate

only one exists
    -> report incomplete keypair
```

`clean` is allowed to remove project-generated keys.

The private key must never be committed to Git.

---

# 48. Public-key installation

The generated public key needs to reach:

```text
/home/dev/.ssh/authorized_keys
```

The cleanest architecture is to generate the preseed dynamically.

The repository should not contain a user-specific public key.

Preferred design:

```text
preseed.cfg.template
        |
        +-- SSH_PUBLIC_KEY placeholder
        |
        v
Python renders generated preseed
        |
        v
temporary HTTP server
        |
        v
Debian installer
        |
        v
authorized_keys
```

This keeps machine-specific state outside source control.

---

# 49. Preseed template

A possible structure is:

```text
preseed/
    preseed.cfg.template
```

containing a placeholder such as:

```text
__SSH_PUBLIC_KEY__
```

Python can replace that with the generated public key before starting the HTTP server.

The generated result should not be committed.

---

# 50. Debian user

The guest user is:

```text
dev
```

The exact user configuration is controlled by:

```yaml
ssh:
    user: dev
```

The installer password comes from:

```yaml
installer:
    password: ...
```

The full user name comes from:

```yaml
installer:
    full_user_name: ...
```

The hostname is generated from the VM name:

```text
debian-dev.local
```

or equivalent configured hostname.

---

# 51. `sudo`

The base system should have:

```text
sudo
```

installed.

The user:

```text
dev
```

should be allowed to use sudo.

The exact passwordless-sudo policy should be explicitly controlled rather than assumed.

If the goal is a development VM where provisioning can execute non-interactively, `provision.sh` must be able to run the required privileged operations without hanging on an interactive password prompt.

This should be solved deliberately through Debian account configuration or the provisioning mechanism, rather than by randomly modifying SSH behavior.

---

# 52. Provisioning design

The base installation should remain small.

The project intentionally divides dependencies into:

```text
boot/install dependencies
```

and:

```text
development dependencies
```

For example:

```text
preseed:
    openssh-server
    sudo
    minimal base packages

provision.sh:
    compiler
    debugger
    git
    Python tooling
    CLI tools
    other development dependencies
```

This makes the VM easier to recreate and maintain.

---

# 53. VS Code use case

The VM is designed to work well with VS Code Remote SSH.

The architecture is:

```text
VS Code
    |
    | SSH
    v
127.0.0.1:2222
    |
    | VirtualBox NAT
    v
Debian VM
    |
    +-- project files
    +-- compiler
    +-- debugger
    +-- development tools
```

The host only needs VS Code's SSH connection to:

```text
127.0.0.1:2222
```

The actual development environment lives inside Debian.

This is useful because the VM becomes a reproducible development environment rather than relying on whatever packages happen to be installed on the 42 host.

---

# 54. No desktop environment

The VM should not install:

```text
GNOME
KDE
XFCE
Firefox
LibreOffice
```

The development workflow is:

```text
host VS Code
      |
      v
SSH
      |
      v
CLI Debian VM
```

There is no reason for the VM to run a graphical desktop.

This reduces:

```text
disk usage
RAM usage
CPU usage
installation time
```

---

# 55. `config.yaml`

There is only one project configuration file:

```text
config.yaml
```

The user should not need to create an additional configuration file.

It contains configuration such as:

```yaml
vm:
    name: debian-dev
    goinfre_root: /goinfre
    disk_directory: debian-vm
    disk_filename: debian-dev.vdi
    cpus: ...
    memory_mb: ...
    disk_mb: ...

debian:
    iso_filename: debian-13.6.0-amd64-netinst.iso
    iso_url: ...
    checksum_url: ...

ssh:
    user: dev
    private_key: state/ssh/debian-vm_ed25519
    public_key: state/ssh/debian-vm_ed25519.pub

installer:
    password: ...
    full_user_name: ...
    timeout_seconds: ...

network:
    ssh_host_port: 2222
```

The exact values belong to the actual repository.

Do not introduce another configuration layer unless there is a concrete requirement.

---

# 56. `main.py` responsibilities

`main.py` owns orchestration.

It should contain functions such as:

```text
load_config()
vm_base_path()
vm_disk_path()
ssh_private_key_path()
ssh_public_key_path()
generate_ssh_keypair()
generate_preseed()
remove_stale_ssh_host_key()
create_vm()
provision_vm()
destroy_vm()
cleanup()
rebuild_vm()
status_vm()
main()
```

It should not contain low-level VirtualBox command construction.

That belongs in:

```text
vm/virtualbox.py
```

Likewise, SSH command construction belongs in:

```text
vm/ssh.py
```

ISO management belongs in:

```text
vm/iso.py
```

Preseed serving belongs in:

```text
vm/preseed.py
```

---

# 57. `vm/virtualbox.py` responsibilities

This module wraps:

```text
VBoxManage
```

and should provide methods such as:

```text
exists()
state()
create()
configure()
create_storage_controller()
create_disk()
attach_disk()
attach_iso()
unattended_install()
start()
stop()
wait_for_poweroff()
delete()
```

The rest of the application should not need to construct raw `VBoxManage` arguments.

This creates a clean abstraction:

```text
main.py
    |
    v
VirtualBox(...)
    |
    v
VBoxManage
```

---

# 58. VirtualBox configuration

The VM should use:

```text
NIC1 = NAT
```

SSH forwarding:

```text
ssh,tcp,127.0.0.1,2222,,22
```

Storage:

```text
SATA Controller
IntelAhci
```

Disk:

```text
VDI
```

Typical attachment:

```text
disk -> SATA port 0
ISO  -> SATA port 1
```

Boot order:

```text
DVD
Disk
None
None
```

The exact VirtualBox command details remain encapsulated in `vm/virtualbox.py`.

---

# 59. Current CLI

The project supports:

```bash
uv run python main.py create
```

```bash
uv run python main.py provision
```

```bash
uv run python main.py destroy
```

```bash
uv run python main.py clean
```

```bash
uv run python main.py rebuild
```

```bash
uv run python main.py status
```

The most useful command for a fresh machine is:

```bash
uv run python main.py rebuild
```

because it guarantees that the VM is recreated from the current project state.

---

# 60. `uv`

The project can be executed using:

```bash
uv run python main.py rebuild
```

A separate:

```bash
uv sync
```

is not required immediately beforehand when using:

```bash
uv run
```

provided the project's dependencies/environment are already correctly described by the project configuration.

`uv run` is responsible for preparing/using the project environment as needed.

The project should not add unnecessary dependency-management complexity.

---

# 61. No additional runtime dependency for ISO/preseed

The ISO manager must not introduce:

```text
requests
wget
curl
aiohttp
```

just to download the ISO.

Python already provides:

```python
urllib.request
```

The preseed server must not introduce:

```text
Flask
FastAPI
aiohttp
```

Python already provides:

```python
http.server
socketserver
threading
```

This keeps the project lightweight and portable.

---

# 62. Error handling philosophy

There are three categories of failures.

### Recoverable/retryable

Examples:

```text
ISO download failed
checksum mismatch
HTTP port collision
SSH not ready yet
```

These should have useful error messages and, where appropriate, retry behavior.

### Existing-state errors

Examples:

```text
VM already exists
partial SSH keypair exists
disk unexpectedly exists
```

These should not silently destroy data.

### Explicit destructive operations

Examples:

```text
clean
destroy
rebuild
```

These are allowed to remove project-owned state.

The application must never silently perform a destructive operation during normal `create`.

---

# 63. VM creation failure behavior

If creation fails:

```text
do not automatically delete the VM
```

The output should explain:

```text
VM was preserved for debugging.
```

and provide:

```bash
python3 main.py status
```

```bash
VBoxManage showvminfo debian-dev
```

```bash
VBoxManage startvm debian-dev --type gui
```

```bash
python3 main.py destroy
```

This is particularly important for debugging Debian installer/preseed failures.

---

# 64. Preseed failure debugging

If SSH never becomes available, inspect the VM using the GUI:

```bash
VBoxManage startvm debian-dev --type gui
```

The installer screen can reveal:

```text
preseed URL unreachable
package installation failure
network failure
partitioning failure
installer prompt
```

The preseed server should also print requests when useful, allowing confirmation that:

```text
Debian installer actually fetched /preseed.cfg
```

The critical diagnostic distinction is:

```text
Did Debian request the preseed?
```

versus:

```text
Did Debian request it but reject its contents?
```

versus:

```text
Did Debian install it but fail to start SSH?
```

---

# 65. Expected successful bootstrap

A successful run should resemble:

```text
[*] Rebuilding VM...
[*] Cleaning project resources...
[+] Cleanup complete.

[*] Debian ISO found: /goinfre/.../debian-13.6.0-amd64-netinst.iso
[*] Checking SHA-512...
[+] ISO SHA-512: OK

[*] Generating SSH ED25519 keypair...
[*] Creating VM...
[*] Configuring VM...
[*] Creating storage controller...
[*] Creating virtual disk...
[*] Attaching virtual disk...
[*] Attaching Debian ISO...

[*] Starting preseed HTTP server...
[+] Preseed server listening on 0.0.0.0:<dynamic-port>
[+] Preseed URL: http://10.0.2.2:<dynamic-port>/preseed.cfg

[*] Configuring unattended Debian installation...
[*] Starting VM...
[+] VM started.

[*] Waiting for Debian installation and SSH...
[+] SSH connection available.

[+] Debian installation complete.
[*] Stopping preseed server...

[*] Running provisioning script...
[+] Provisioning complete.

[+] Rebuild complete.
```

---

# 66. Expected final SSH usage

The user should be able to run:

```bash
ssh \
    -i state/ssh/debian-vm_ed25519 \
    -p 2222 \
    dev@127.0.0.1
```

without entering the Debian account password.

The same connection information should be usable by VS Code Remote SSH.

---

# 67. Expected development workflow at 42

The intended workflow is:

```text
Arrive at 42 machine A
        |
        v
VM exists on /goinfre
        |
        v
Use VM normally
```

Then move to another machine:

```text
Machine B
    |
    v
same project repository
    |
    v
uv run python main.py rebuild
    |
    +-- ISO downloaded if necessary
    +-- VM recreated on local /goinfre
    +-- Debian installed
    +-- SSH configured
    +-- provisioning executed
    |
    v
development environment ready
```

This avoids depending on the VM being physically located on the previous machine.

---

# 68. What is intentionally persistent

The repository contains the automation.

The VM itself is disposable.

Potential persistent project state:

```text
config.yaml
scripts/provision.sh
preseed configuration/template
source code
```

Machine-specific state:

```text
state/ssh/
```

should generally be treated as generated state.

Large runtime state:

```text
/goinfre/.../debian-vm/
```

is disposable.

Large ISO:

```text
/goinfre/.../debian-13.6.0-amd64-netinst.iso
```

can be retained between VM rebuilds to avoid downloading it again.

---

# 69. What should not be committed

Do not commit:

```text
state/ssh/debian-vm_ed25519
```

The private key is secret material.

Generated VM state should also not be committed:

```text
.vbox
.vdi
/goinfre state
```

The repository should contain the instructions required to recreate those artifacts.

---

# 70. Important architectural principle

The repository should be treated as the source of truth.

The VM should not be treated as the source of truth.

The desired model is:

```text
Git repository
    |
    +-- config
    +-- preseed
    +-- provisioning
    +-- automation
    |
    v
reproducible VM
```

rather than:

```text
manually configured VM
    |
    +-- unknown state
    +-- manually installed packages
    +-- undocumented changes
```

This is the main reason the project exists.

---

# 71. Things that must not regress

Future changes must preserve all of the following:

```text
ISO can be automatically downloaded.
ISO is SHA-512 verified.
ISO lives on /goinfre.
VM lives on /goinfre.
VM resources are configurable.
VM uses NAT.
SSH is forwarded through 127.0.0.1:2222.
SSH uses generated ED25519 keys.
SSH does not require interactive passwords during normal use.
Disposable VM host keys do not cause known_hosts failures.
Debian installation is CLI-only.
openssh-server is installed during installation.
sudo is installed.
Preseed is served temporarily.
Preseed server uses a dynamically selected port.
Preseed server is reachable from the NAT guest.
VM is started exactly once.
SSH readiness is waited for.
Provisioning is separate from installation.
create does not automatically destroy failed VMs.
clean/rebuild explicitly destroy project state.
Stale VirtualBox directories are handled.
No unnecessary external dependencies are introduced.
```

---

# 72. Things that previously failed

These failures are part of the project's history and should not be reintroduced.

### Fixed-port preseed server

Bad:

```python
PreseedServer(..., port=8080)
```

Failure:

```text
[Errno 98] Address already in use
```

Correct:

```text
dynamic port
```

---

### Wrong host address in preseed URL

Bad:

```text
http://127.0.0.1:<port>/preseed.cfg
```

from inside the guest.

Correct for VirtualBox NAT:

```text
http://10.0.2.2:<port>/preseed.cfg
```

assuming the VirtualBox NAT host address behaves as expected on the target environment.

---

### Assuming `unattended install` means installation finished

Bad:

```text
VBoxManage unattended install
    =
Debian is ready
```

Correct:

```text
unattended install configuration
        +
VM start
        +
installer
        +
reboot
        +
SSH readiness
        =
VM ready
```

---

### Starting the VM twice

Bad:

```text
start()
...
start()
```

Correct:

```text
one start()
```

---

### Stopping the preseed server too early

Bad:

```text
configure unattended install
stop HTTP server
start VM
```

Correct:

```text
start HTTP server
configure unattended install
start VM
wait for installation/SSH
stop HTTP server
```

---

### Treating SSH host-key changes as an authentication problem

Bad assumption:

```text
new VM
    ->
SSH authentication broken
```

Actual issue:

```text
new VM
    ->
new SSH host key
    ->
old known_hosts entry no longer matches
```

The disposable VM SSH client intentionally avoids persistent host-key storage.

---

### Expecting `--package-selection-adjustment` to install arbitrary packages

Bad:

```text
--package-selection-adjustment minimal openssh-server
```

Correct conceptual model:

```text
package-selection-adjustment
    =
VirtualBox installation adjustment

preseed
    =
Debian package selection
```

---

### Checking only the VDI during cleanup

Bad:

```text
remove disk
remove base directory
```

while leaving:

```text
/goinfre/.../debian-vm/debian-dev/debian-dev.vbox
```

Correct:

```text
clean VirtualBox registration
+
clean stale VM-specific directory
+
clean leftover disk if safe
```

---

# 73. Core implementation blueprint

The final architecture should be:

```text
                         ┌───────────────────────┐
                         │       config.yaml     │
                         └───────────┬───────────┘
                                     │
                                     v
                         ┌───────────────────────┐
                         │       main.py         │
                         │     orchestration     │
                         └──────┬────┬─────┬─────┘
                                │    │     │
                ┌───────────────┘    │     └────────────────┐
                v                    v                      v
       ┌────────────────┐   ┌────────────────┐    ┌────────────────┐
       │    iso.py      │   │ virtualbox.py  │    │    ssh.py      │
       │                │   │                │    │                │
       │ download ISO   │   │ VBoxManage     │    │ SSH client     │
       │ SHA-512 verify │   │ VM lifecycle   │    │ key auth       │
       └────────────────┘   └───────┬────────┘    └────────────────┘
                                    │
                                    v
                           ┌──────────────────┐
                           │   preseed.py     │
                           │                  │
                           │ temporary HTTP   │
                           │ server           │
                           └────────┬─────────┘
                                    │
                                    v
                           ┌──────────────────┐
                           │ Debian installer │
                           │                  │
                           │ minimal CLI      │
                           │ sudo             │
                           │ openssh-server   │
                           │ authorized_keys  │
                           └────────┬─────────┘
                                    │
                                    v
                           ┌──────────────────┐
                           │  Debian VM       │
                           │                  │
                           │  dev             │
                           │  sshd            │
                           │  NAT             │
                           └────────┬─────────┘
                                    │
                             localhost:2222
                                    │
                                    v
                           ┌──────────────────┐
                           │ SSHProvisioner   │
                           └────────┬─────────┘
                                    │
                                    v
                           ┌──────────────────┐
                           │ provision.sh     │
                           │                  │
                           │ development      │
                           │ dependencies     │
                           └──────────────────┘
```

---

# 74. Final design philosophy

The project is fundamentally a **reproducible VM factory**, not merely a VirtualBox wrapper.

Its key properties are:

```text
Disposable
Reproducible
Minimal
Configurable
SSH-accessible
Developer-oriented
Storage-efficient
42-friendly
```

The VM can disappear.

The machine can change.

The `/goinfre` location can change.

The ISO can disappear.

The SSH keys can be regenerated.

The entire environment can still be reconstructed from the repository with:

```bash
uv run python main.py rebuild
```

That is the central design goal.
