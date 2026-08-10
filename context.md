Use the following as the handoff context for another LLM. It contains the project architecture, intended design, current files, decisions already made, and the exact failures encountered.

# Debian VM Automation Project — Full Handoff Context

## 1. Project goal

This project automates creation of a minimal Debian development VM using VirtualBox.

Host:

* Linux
* VirtualBox
* Python 3
* Project located at:
  `/home/mberraho/projects/VM/debian-automation`

VM:

* Debian 13.6.0 amd64
* VM name: `debian-dev`
* Intended use: coding/development
* Headless operation
* SSH access from host
* NAT port forwarding:
  `127.0.0.1:2222 -> guest:22`

The VM should be minimal. The previous VirtualBox unattended installation installed unnecessary desktop packages such as Firefox and LibreOffice. The goal is to avoid those packages.

The project initially attempted to rely entirely on `VBoxManage unattended install`, but that did not reliably provide the required `openssh-server` package. The current direction is therefore:

**VirtualBox unattended installation + Debian preseed configuration served over HTTP.**

The project no longer intends to manually install packages after login just to make SSH work.

---

# 2. Current project architecture

Current tree:

```text
.
├── config.yaml
├── main.py
├── preseed
│   └── preseed.cfg
├── requirements.txt
├── scripts
│   └── provision.sh
├── state
│   └── ssh
└── vm
    ├── __init__.py
    ├── ssh.py
    └── virtualbox.py
```

`state/ssh` contains project-generated SSH keys.

The old `__pycache__` directories are irrelevant.

---

# 3. Important architectural decision

No custom ISO is being built.

No Debian netboot infrastructure is being installed.

The intended mechanism is:

```text
Python
  |
  +-- start temporary HTTP server
  |       |
  |       +-- /preseed.cfg
  |
  +-- VBoxManage unattended install
  |       |
  |       +-- extra Debian kernel parameters
  |               |
  |               +-- auto=true
  |               +-- priority=critical
  |               +-- preseed/url=http://<host>:8080/preseed.cfg
  |
  +-- start VM
  |
  +-- Debian installer fetches preseed.cfg
  |
  +-- Debian installer installs only required packages
  |       |
  |       +-- openssh-server
  |       +-- sudo
  |       +-- development utilities as explicitly configured
  |
  +-- VM boots
  |
  +-- SSH becomes available
  |
  +-- SSHProvisioner runs scripts/provision.sh
```

The HTTP server exists only during installation.

---

# 4. Why preseed was introduced

VirtualBox's:

```text
VBoxManage unattended install
```

supports:

```text
--package-selection-adjustment=<keyword>
```

but this is not a reliable mechanism for explicitly declaring Debian package selection.

The command help showed:

```text
--package-selection-adjustment=<keyword>
    Adjustments to the guest OS packages/components selection.
```

The attempted command used:

```text
--package-selection-adjustment minimal openssh-server
```

which is incorrect because `openssh-server` is not an additional argument to that option.

The later version correctly used:

```text
--package-selection-adjustment
minimal
```

but SSH still was not reliably installed.

Therefore package selection belongs in Debian's preseed configuration.

---

# 5. Debian ISO

Current ISO:

```text
/goinfre/mberraho/debian-13.6.0-amd64-netinst.iso
```

---

# 6. VM filesystem

Configured VM base directory:

```text
/goinfre/mberraho/debian-vm
```

VM disk:

```text
/goinfre/mberraho/debian-vm/debian-dev.vdi
```

The actual VirtualBox VM directory is currently:

```text
/goinfre/mberraho/debian-vm/debian-dev/
```

---

# 7. SSH configuration

Guest user:

```text
dev
```

Host:

```text
127.0.0.1
```

Host SSH port:

```text
2222
```

Guest SSH port:

```text
22
```

VirtualBox forwarding:

```text
127.0.0.1:2222 -> VM:22
```

Manual connection:

```bash
ssh -p 2222 dev@127.0.0.1
```

The project also generates an SSH key under:

```text
/home/mberraho/projects/VM/debian-automation/state/ssh/debian-vm_ed25519
/home/mberraho/projects/VM/debian-automation/state/ssh/debian-vm_ed25519.pub
```

The key generation logic itself still needs to be verified/implemented correctly if it is not already handled elsewhere.

---

# 8. SSH host-key problem

When rebuilding the VM, Debian generates a new SSH host key.

Previously the host produced:

```text
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
...
Offending ECDSA key in /home/mberraho/.ssh/known_hosts:9
Host for [127.0.0.1]:2222 has changed
```

The intended solution is NOT to repeatedly run:

```bash
ssh-keygen -R '[127.0.0.1]:2222'
```

Instead, all automated SSH commands should use:

```text
-o StrictHostKeyChecking=no
-o UserKnownHostsFile=/dev/null
```

because this VM is disposable and the SSH endpoint is a local NAT-forwarded development VM.

These options belong in:

```text
vm/ssh.py
```

inside the single common SSH command builder.

Do not duplicate the options throughout `main.py`.

---

# 9. Current SSHProvisioner design

The common command builder should conceptually be:

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

Then:

```python
wait_for_ssh()
run()
run_script()
```

must all use `self.command(...)`.

This prevents inconsistent SSH behavior.

---

# 10. Important distinction: SSH client vs SSH server

The following options:

```text
StrictHostKeyChecking=no
UserKnownHostsFile=/dev/null
```

only affect the host-side SSH client.

They do NOT install or start `openssh-server` inside Debian.

The previous error:

```text
kex_exchange_identification: read: Connection reset by peer
Connection reset by peer port 2222
```

indicates that the forwarding path reached the guest but the guest-side SSH service was not accepting the connection.

Therefore the real fix is to make the Debian installer install and enable:

```text
openssh-server
```

through preseed.

---

# 11. Temporary HTTP server

A `PreseedServer` class was introduced.

Its intended responsibility:

```text
serve:
    ROOT/preseed/preseed.cfg

on:
    0.0.0.0:<some-port>

while:
    Debian installer is running
```

Then:

```text
preseed URL:
http://<host-address>:<port>/preseed.cfg
```

is supplied to the Debian installer through Linux kernel parameters.

The first implementation attempted:

```text
port=8080
```

and failed with:

```text
[ERROR] Could not start preseed HTTP server on port 8080:
[Errno 98] Address already in use
```

Therefore the implementation must NOT blindly assume port 8080 is free.

Preferred design:

```text
bind host:
    0.0.0.0

port:
    dynamically select a free ephemeral port
```

or configure a port from `config.yaml` and detect collisions.

Dynamic port selection is preferable.

A temporary server should use Python's standard library:

```python
http.server
socketserver
threading
socket
```

No external HTTP dependency is needed.

---

# 12. Critical networking issue with preseed HTTP server

The Debian installer runs inside the VM.

The VM uses:

```text
NIC1 = NAT
```

The host's:

```text
127.0.0.1
```

is NOT automatically reachable as the host from inside a VirtualBox NAT guest.

Therefore this is wrong:

```text
preseed/url=http://127.0.0.1:8080/preseed.cfg
```

because inside the guest, `127.0.0.1` refers to the guest itself.

The HTTP server must be reachable from the guest.

There are two viable approaches:

### Approach A: VirtualBox NAT host loopback access

Use the VirtualBox NAT gateway/host address available to the guest, typically:

```text
10.0.2.2
```

and bind the HTTP server to:

```text
0.0.0.0
```

Then use:

```text
http://10.0.2.2:<port>/preseed.cfg
```

This should be verified on the actual VirtualBox version/platform.

### Approach B: Explicit NAT port forwarding

Create a temporary VirtualBox forwarding rule from a host port to the host HTTP server.

However, because the host HTTP server itself is on the host, this approach is unnecessarily complicated.

Preferred first implementation:

```text
HTTP server:
0.0.0.0:<dynamic-port>

Debian installer:
http://10.0.2.2:<dynamic-port>/preseed.cfg
```

If macOS/VirtualBox networking behavior differs, verify with a small test.

---

# 13. Existing main.py problems

The supplied `main.py` had several bugs.

The relevant incorrect sequence was:

```python
server = PreseedServer(
    ROOT / "preseed",
    port=8080,
)

server.start()

try:
    vbox.unattended_install(
        ...
        preseed_url=server.url("preseed.cfg"),
    )

    vbox.start(headless=True)

    ssh.wait_for_ssh(...)

finally:
    server.stop()
```

Problems:

1. `PreseedServer` was not imported.
2. `ssh` was used before being created.
3. The VM was started inside the preseed server block and then started AGAIN later.
4. `server.stop()` could execute while installation still required the server depending on how the lifecycle was structured.
5. Fixed port 8080 caused:

   ```text
   [Errno 98] Address already in use
   ```
6. The code said:

   ```text
   "[+] Unattended installation configured."
   ```

   before installation was actually complete.
7. `rebuild_vm()` called:

   ```python
   cleanup(cfg)
   create_vm(cfg)
   provision_vm(cfg)
   ```

   but `create_vm()` already waits for SSH and should ideally leave the VM in a consistent ready state.
8. SSH key generation was discussed but the shown `main.py` only created the parent directory; it did not actually invoke `ssh-keygen`.
9. Cleanup behavior needs to account for VirtualBox deleting the VM and its disk with:

   ```text
   unregistervm --delete
   ```

   so manually unlinking the VDI may be redundant.
10. Error handling around VirtualBox's occasional non-zero `unregistervm` behavior needs to be robust.

---

# 14. Existing VirtualBox.py design

The current class is a wrapper around:

```text
VBoxManage
```

with methods:

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
wait_for_poweroff()
stop()
delete()
```

---

# 15. Current VirtualBox configuration

CPU and memory come from config.

Network:

```text
--nic1 nat
```

Boot order:

```text
dvd
disk
none
none
```

NAT SSH forwarding:

```text
--nat-pf1
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

ISO attached at SATA port 1.

Disk attached at SATA port 0.

---

# 16. Current unattended_install problem

The current version looked approximately like:

```python
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
    "--package-selection-adjustment",
    "minimal",
)
```

This correctly uses:

```text
--package-selection-adjustment minimal
```

but does not provide Debian preseed configuration.

The new implementation should add:

```text
--extra-install-kernel-parameters
```

with parameters that tell the Debian installer to retrieve the preseed file.

Conceptually:

```text
auto=true priority=critical preseed/url=http://10.0.2.2:<PORT>/preseed.cfg
```

The exact quoting/argument handling must be implemented so `VBoxManage` receives it as one argument.

---

# 17. Debian preseed requirements

The preseed must produce a minimal CLI development VM.

At minimum it needs to configure:

```text
Debian mirror
locale
keyboard
timezone
hostname
user
password or password hash
partitioning
bootloader
package selection
SSH server
```

Most importantly:

```text
openssh-server
```

must be installed.

The package selection should explicitly avoid desktop packages.

Do NOT select:

```text
desktop
gnome
kde
xfce
firefox
libreoffice
```

The intended base is a server/CLI system.

A minimal package list should include only what is needed, e.g.:

```text
openssh-server
sudo
ca-certificates
curl
git
build-essential
```

Additional development tools can be installed later through:

```text
scripts/provision.sh
```

The exact package list should be deliberately controlled.

---

# 18. Important preseed package-selection concept

Debian preseed package selection should not blindly copy the old full Debian task selection.

The installer should avoid desktop tasks.

For example, package selection should conceptually look like:

```text
tasksel tasksel/first multiselect standard
d-i pkgsel/include string openssh-server sudo ca-certificates curl git build-essential
```

But this must be checked against the actual Debian 13 installer behavior.

If the goal is truly minimal, `standard` itself may pull more packages than desired.

A better approach is to explicitly understand what Debian installer task selection is enabled by default and disable desktop/task packages.

The generated preseed should therefore be tested rather than assuming that:

```text
tasksel/first multiselect
```

means zero packages.

---

# 19. SSH authentication design

The Debian installer needs to create:

```text
dev
```

with the password from:

```text
cfg["installer"]["password"]
```

This password is currently used by VirtualBox's unattended installer.

The project-generated SSH public key should ideally be installed into:

```text
/home/dev/.ssh/authorized_keys
```

This can be done in the preseed via late command or after first SSH login.

The simpler staged design is:

1. Preseed creates `dev` with password.
2. Preseed installs `openssh-server`.
3. VM boots.
4. SSH is reachable.
5. `SSHProvisioner` uses the password initially if key auth is not yet configured.

However, the current `SSHProvisioner` is designed around:

```text
-i state/ssh/debian-vm_ed25519
```

so public-key authentication must eventually be configured.

The cleanest design is to have preseed place the public key into `authorized_keys`, meaning the VM is immediately reachable using the generated key.

---

# 20. SSH key generation

Current intended key paths:

```text
state/ssh/debian-vm_ed25519
state/ssh/debian-vm_ed25519.pub
```

The project should generate them automatically if missing.

Conceptually:

```bash
ssh-keygen \
    -t ed25519 \
    -f state/ssh/debian-vm_ed25519 \
    -N ""
```

Do not regenerate the key every time `create` runs unless the old key has been deliberately cleaned.

`clean` can remove the project-owned keys.

---

# 21. Preseed public-key handling

Because `preseed.cfg` needs the public key, there are two possible designs.

### Option 1 — generate preseed dynamically

Recommended.

Do not hardcode a user-specific public key into the repository.

Python can:

1. generate/read the public key
2. load a template
3. substitute the public key
4. write a temporary/generated preseed file
5. serve that generated file

For example:

```text
preseed/preseed.cfg.template
```

with:

```text
{{SSH_PUBLIC_KEY}}
```

Then Python renders:

```text
state/preseed.cfg
```

and serves that.

### Option 2 — preseed installs password SSH first

Simpler but less secure and less aligned with the project's key-based SSH design.

Option 1 is preferred.

---

# 22. Current preseed directory

Current tree contains:

```text
preseed/preseed.cfg
```

But it may need to become:

```text
preseed/
    preseed.cfg.template
```

or remain:

```text
preseed/preseed.cfg
```

if the public key is inserted through a separate mechanism.

Do not commit a private key.

---

# 23. Provisioning stage

After SSH becomes available:

```text
scripts/provision.sh
```

should install/configure development tooling not needed during Debian installation.

This is the correct place for things such as:

```text
git
curl
wget
build-essential
python3
python3-pip
python3-venv
pkg-config
clang
gdb
strace
ripgrep
tmux
vim/neovim
```

Only packages actually desired should be included.

The base Debian installation should remain minimal.

---

# 24. Current command-line interface

`main.py` supports:

```text
create
provision
destroy
clean
rebuild
status
```

Expected usage:

```bash
python3 main.py create
```

```bash
python3 main.py provision
```

```bash
python3 main.py destroy
```

```bash
python3 main.py clean
```

```bash
python3 main.py rebuild
```

```bash
python3 main.py status
```

Debug mode:

```bash
python3 main.py create --keep-on-failure
```

---

# 25. Important lifecycle decision

`create` should ideally perform the complete VM bootstrap:

```text
create VM
configure VM
create disk
attach disk
attach ISO
generate SSH key
start temporary preseed HTTP server
configure unattended install with preseed kernel parameters
start VM
wait for SSH
stop preseed server
return success
```

Then:

```text
provision
```

is responsible only for running:

```text
scripts/provision.sh
```

over SSH.

`rebuild` should therefore be:

```text
clean
create
provision
```

---

# 26. Current failure: HTTP server port collision

Exact error:

```text
[!] VM creation failed.
[!] VM was preserved for debugging.
[ERROR] Could not start preseed HTTP server on port 8080:
[Errno 98] Address already in use
```

Cause:

```text
port 8080 is already occupied.
```

Required fix:

Do not hard-code:

```python
PreseedServer(..., port=8080)
```

unless collision handling is implemented.

Prefer:

```python
PreseedServer(
    ROOT / "preseed",
    host="0.0.0.0",
    port=0,
)
```

where:

```text
port=0
```

means the OS chooses an unused ephemeral port.

The server must expose the actual selected port through something like:

```python
server.port
```

and:

```python
server.url("preseed.cfg")
```

must return the reachable guest URL, not `127.0.0.1`.

For VirtualBox NAT, likely:

```text
http://10.0.2.2:<selected_port>/preseed.cfg
```

---

# 27. Current failure: SSH connection reset

Exact error:

```text
ssh -p 2222 dev@127.0.0.1

kex_exchange_identification: read: Connection reset by peer
Connection reset by 127.0.0.1 port 2222
```

This is not caused by:

```text
StrictHostKeyChecking
```

It means SSH is not yet usable in the guest.

Likely causes:

1. Debian installation has not finished.
2. `openssh-server` was not installed.
3. `sshd` is not running.
4. The VM is still in installer state.
5. The preseed was not fetched.
6. The preseed package selection failed.
7. NAT forwarding is correct but guest port 22 is closed.

The automation must wait for actual SSH readiness instead of assuming the VM is ready immediately after `startvm`.

---

# 28. Critical race condition to avoid

Do not do:

```python
vbox.unattended_install(...)
vbox.start()

server.stop()
```

immediately after `start()`.

The Debian installer still needs the HTTP server while installation is running.

The HTTP server must remain alive until the installer has fetched the preseed.

At minimum:

```text
start server
configure VM with preseed URL
start VM
wait until installer is finished / SSH available
stop server
```

A robust implementation can keep the server alive until SSH is available.

---

# 29. Another critical issue: VirtualBox unattended install semantics

`VBoxManage unattended install` primarily configures the VM and creates unattended installation files/scripts.

It does not mean the Debian installation is synchronously complete when the command returns.

Therefore:

```python
vbox.unattended_install(...)
```

must NOT be interpreted as:

```text
Debian installation finished
```

The VM must then be started and observed.

The actual completion signal in this project is:

```text
SSH login succeeds
```

provided the preseed guarantees that `openssh-server` is installed and started.

---

# 30. VirtualBox delete failure previously observed

Previous cleanup output:

```text
[*] Unregistering VM 'debian-dev'...
$ VBoxManage unregistervm debian-dev --delete
0%...10%...20%...30%...40%...50%...60%...70%...80%...90%...100%
[+] Cleanup complete.
[+] Cleanup complete.

[ERROR] VBoxManage failed with exit code 2
```

This indicates VirtualBox may successfully remove the VM/storage while returning a non-zero exit code during deletion.

The `delete()` method should therefore:

1. run `unregistervm --delete`
2. inspect the return code
3. if non-zero, check `exists()`
4. if the VM no longer exists, consider deletion successful
5. only raise if the VM still exists

The current code already attempted this behavior.

However, the surrounding cleanup logic should avoid printing:

```text
[+] Cleanup complete.
```

twice.

There should be one clear success path.

---

# 31. Cleanup behavior

`clean` should remove:

```text
VM registration
VM storage
VDI if it still exists
project-generated SSH keys
empty state directories
```

But do not blindly unlink a VDI if VirtualBox still owns it.

Preferred order:

```text
VirtualBox unregistervm --delete
verify VM gone
verify disk gone
only remove leftover disk if safe
remove generated SSH keys
remove empty directories
```

---

# 32. Important Python syntax corrections

The original pasted source contains formatting corruption such as:

```python
ROOT = Path(**file**)
```

The actual Python must be:

```python
ROOT = Path(__file__).resolve().parent
```

Likewise:

```python
if **name** == "**main**":
```

must be:

```python
if __name__ == "__main__":
    main()
```

The indentation shown in several pasted snippets is also Markdown-corrupted. The final files must use normal Python indentation.

---

# 33. Required files for the next implementation

The next LLM should produce/fix these files:

```text
main.py
vm/virtualbox.py
vm/ssh.py
preseed.py
```

Potentially also:

```text
preseed/preseed.cfg
```

or:

```text
preseed/preseed.cfg.template
```

if dynamic public-key injection is implemented.

The current user explicitly requested a complete correction of these scripts.

---

# 34. Desired `preseed.py`

A dedicated module should encapsulate the HTTP server.

Suggested interface:

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

Requirements:

* standard library only
* dynamic port support
* background thread
* clean shutdown
* verify directory exists
* serve only intended preseed directory
* expose selected port
* URL should be reachable from Debian installer
* do not use `127.0.0.1` in the guest URL

---

# 35. Desired VirtualBox.unattended_install interface

It should become approximately:

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
```

It should call:

```text
VBoxManage unattended install
```

with:

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

The kernel parameter value should contain:

```text
auto=true
priority=critical
preseed/url=<URL>
```

Potentially Debian installer parameters such as:

```text
netcfg/disable_autoconfig=false
```

can be added if necessary, but do not add arbitrary parameters without a reason.

---

# 36. Important package-selection goal

The Debian installer must NOT install the desktop environment.

The resulting VM should be CLI-only.

The preseed should explicitly control:

```text
tasksel
pkgsel/include
```

and avoid desktop tasks.

The required SSH package is:

```text
openssh-server
```

The preseed should ensure it is installed before first boot.

---

# 37. Expected final bootstrap

The intended successful log should resemble:

```text
[*] VM name: debian-dev
[*] VM directory: /goinfre/mberraho/debian-vm
[*] VM disk: /goinfre/mberraho/debian-vm/debian-dev.vdi
[*] Debian ISO: /goinfre/mberraho/debian-13.6.0-amd64-netinst.iso

[*] Generating SSH key...
[*] Creating VM...
[*] Configuring VM...
[*] Creating storage controller...
[*] Creating virtual disk...
[*] Attaching virtual disk...
[*] Attaching Debian ISO...

[*] Starting preseed HTTP server...
[+] Preseed server listening on 0.0.0.0:<dynamic-port>
[+] Preseed URL: http://10.0.2.2:<dynamic-port>/preseed.cfg

[*] Preparing unattended Debian installation...
[*] Starting VM...
[+] VM started.

[*] Waiting for Debian installation / SSH...
[+] SSH is ready.

[+] Debian installation complete.
[+] VM creation complete.
```

Then:

```bash
python3 main.py provision
```

should run:

```text
scripts/provision.sh
```

through SSH.

---

# 38. Current state

The project is NOT yet in a known-good state.

The main unresolved problems are:

1. Correctly integrate Debian preseed.
2. Correctly inject preseed URL into VirtualBox unattended installation.
3. Run the temporary HTTP server on a dynamically allocated port.
4. Make the server reachable from the NAT guest.
5. Ensure `openssh-server` is installed through preseed.
6. Ensure SSH is running after installation.
7. Ensure the generated SSH public key is installed for `dev`.
8. Ensure `SSHProvisioner` uses:

   ```text
   StrictHostKeyChecking=no
   UserKnownHostsFile=/dev/null
   ```
9. Remove the double-VM-start bug.
10. Ensure `ssh` is constructed before it is used.
11. Make cleanup robust against VirtualBox exit code 2 after successful deletion.
12. Ensure the base Debian installation remains CLI/minimal and does not install Firefox, LibreOffice, or a desktop environment.
13. Avoid fixed port 8080 because it is already occupied on the host.

---

# 39. Most recent exact failure

Command:

```bash
python3 main.py create
```

Output:

```text
[*] VM name: debian-dev
[*] VM directory: /goinfre/mberraho/debian-vm
[*] VM disk: /goinfre/mberraho/debian-vm/debian-dev.vdi
[*] Debian ISO: /goinfre/mberraho/debian-13.6.0-amd64-netinst.iso
[*] SSH private key: /home/mberraho/projects/VM/debian-automation/state/ssh/debian-vm_ed25519
[*] SSH public key: /home/mberraho/projects/VM/debian-automation/state/ssh/debian-vm_ed25519.pub
[!] VM creation failed.
[!] VM was preserved for debugging.
[ERROR] Could not start preseed HTTP server on port 8080: [Errno 98] Address already in use
```

After that, manual SSH produced:

```bash
ssh -p 2222 dev@127.0.0.1
```

and:

```text
kex_exchange_identification: read: Connection reset by peer
Connection reset by 127.0.0.1 port 2222
```

This is expected if the VM is not fully installed or `openssh-server` is absent.

---

# 40. What NOT to do

Do not:

```text
install openssh-server manually after every VM creation
```

Do not:

```text
use Firefox/LibreOffice desktop installation
```

Do not:

```text
hard-code HTTP port 8080
```

Do not:

```text
use 127.0.0.1 as the Debian guest's address to reach the host HTTP server
```

Do not:

```text
append openssh-server after --package-selection-adjustment minimal
```

Do not:

```text
start the VM twice
```

Do not:

```text
stop the preseed HTTP server immediately after VBoxManage unattended install returns
```

Do not:

```text
put SSH host-key options in VirtualBox configuration
```

Do not:

```text
run ssh-keygen -R on every connection
```

Do not:

```text
hard-code a user's SSH public key into source control
```

---

# 41. Core implementation principle

Separate the system into four layers:

```text
VirtualBox layer
    |
    +-- VM lifecycle
    +-- disks
    +-- ISO
    +-- NAT
    +-- unattended-install configuration

Preseed HTTP layer
    |
    +-- temporarily serves Debian installer configuration

Debian installer
    |
    +-- creates user
    +-- installs minimal system
    +-- installs openssh-server
    +-- installs SSH authorized key
    +-- boots

SSH layer
    |
    +-- waits for SSH
    +-- executes provisioning script
```

Do not mix these responsibilities.

The next implementation should first make `create` reliably produce a minimal Debian VM with working key-based SSH. Only after that should additional provisioning complexity be added.
