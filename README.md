# Debian VM Automation

## Why this project exists

At 42, the local machines have limited disk space, while `/goinfre` provides significantly more space for development. The problem is that `/goinfre` is tied to the physical machine you are currently using.

When you switch computers, you either need to reconnect to the machine where your VM and files are stored or recreate your development environment.

This project makes recreating the environment cheap and reproducible.

The VM can be created on demand with a single command:

```bash
uv run python main.py rebuild
```

The project automatically handles:

- Creating the Debian VM with VirtualBox
- Downloading the Debian ISO when necessary
- Verifying the ISO using Debian's official SHA-512 checksum
- Creating the VM disk on `/goinfre`
- Generating an SSH keypair at each creation
- Configuring SSH access to the VM
- Installing and configuring the Debian environment
- Provisioning additional development dependencies
- Connecting to the VM through SSH

Additional tools and dependencies can be added to:

```text
scripts/provision.sh
```

This makes the provisioning process easy to extend without modifying the Python code.

The resulting VM is also convenient for development with VS Code through SSH. Your development environment stays isolated inside the Debian VM while the VM itself can be recreated whenever you move to another 42 machine.

The main goal is therefore **fast, reproducible development environments that are independent of the physical 42 machine you happen to be using**.

## Requirements

- Linux
- VirtualBox
- Python 3.12+
- `uv`

The Debian ISO is downloaded automatically if it is not already present. Its SHA-512 checksum is verified against Debian's official checksum manifest.

## Usage

Install the Python environment:

```bash
uv sync
```

Create and install the VM:

```bash
uv run python main.py create
```

Provision the VM:

```bash
uv run python main.py provision
```

Or perform a complete rebuild:

```bash
uv run python main.py rebuild
```

Check the VM status:

```bash
uv run python main.py status
```

Destroy the VM:

```bash
uv run python main.py destroy
```

Remove the VM, disk, and generated SSH keys:

```bash
uv run python main.py clean
```

## SSH

After creation, SSH is available through the configured local port:

```bash
ssh -i state/ssh/debian-vm_ed25519 \
    -p 2222 \
    dev@127.0.0.1
```

The SSH keypair is generated automatically and should not be committed to Git.

## Configuration

## VM Specifications

The default VM is configured for a lightweight development environment:

- **Disk:** 10 GB virtual disk
- **RAM:** 4 GB
- **CPU:** 4 cores
- **Swap:** approximately 572 MB
- **OS:** Debian 13

The disk is stored under `/goinfre`, so it does not consume the limited space of the machine's main filesystem.

These specifications can be changed in `config.yaml`:

The VM is intentionally configurable so you can adapt it to the resources available on the 42 machine you are currently using.

The default configuration is designed to provide a usable development environment without consuming excessive resources.

`config.yaml` contains the project configuration:

- VM resources
- Debian ISO filename
- SSH port
- VM username
- installer settings
- preseed server port

The `/goinfre` path automatically uses the current system username, so users do not need to replace another user's login manually.

## Generated Files

The following files are generated locally and should **not** be committed:

```text
state/
preseed/preseed.cfg
```

Only the preseed template is tracked:

```text
preseed/preseed.template.cfg
```

The generated `preseed.cfg` contains the user's generated SSH public key and must remain local.

## Reproducibility

The project uses:

- `pyproject.toml` for Python project configuration
- `uv.lock` for reproducible Python dependencies
- Debian's official SHA-512 checksum manifest to verify the installer ISO

Run:

```bash
uv sync
```

to recreate the Python environment from `uv.lock`.