from __future__ import annotations

import getpass
import hashlib
import urllib.request
from pathlib import Path


def resolve_iso_path(
    goinfre_root: str,
    iso_filename: str,
) -> Path:
    return (
        Path(goinfre_root).expanduser()
        / getpass.getuser()
        / iso_filename
    ).resolve()


class ISOError(RuntimeError):
    pass


class ISOManager:
    def __init__(
        self,
        iso_path: Path,
        iso_url: str,
        checksum_url: str,
    ):
        self.iso_path = Path(iso_path)
        self.iso_url = iso_url
        self.checksum_url = checksum_url

    def _download(
        self,
        url: str,
        destination: Path,
    ) -> None:
        print(f"[*] Downloading: {url}")
        print(f"[*] Destination: {destination}")

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with urllib.request.urlopen(url) as response:
            total = response.headers.get("Content-Length")
            total_size = int(total) if total else None

            downloaded = 0

            with destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)

                    if not chunk:
                        break

                    output.write(chunk)
                    downloaded += len(chunk)

                    if total_size:
                        percent = downloaded * 100 // total_size

                        print(
                            f"\r    "
                            f"{downloaded / 1024 / 1024:.1f} MB "
                            f"({percent}%)",
                            end="",
                            flush=True,
                        )
                    else:
                        print(
                            f"\r    "
                            f"{downloaded / 1024 / 1024:.1f} MB",
                            end="",
                            flush=True,
                        )

        print()

    def _download_checksum_manifest(self) -> str:
        print(
            f"[*] Downloading checksum manifest: "
            f"{self.checksum_url}"
        )

        with urllib.request.urlopen(
            self.checksum_url
        ) as response:
            return response.read().decode("utf-8")

    def _expected_sha512(self) -> str:
        filename = self.iso_path.name
        manifest = self._download_checksum_manifest()

        for line in manifest.splitlines():
            line = line.strip()

            if not line:
                continue

            parts = line.split()

            if len(parts) != 2:
                continue

            checksum, manifest_filename = parts

            # Handle both:
            #
            #   hash  filename.iso
            #   hash *filename.iso
            #
            manifest_filename = manifest_filename.lstrip("*")
            manifest_filename = Path(
                manifest_filename
            ).name

            if manifest_filename == filename:
                return checksum.lower()

        raise ISOError(
            f"Could not find {filename} in "
            f"{self.checksum_url}"
        )

    def _sha512(self, path: Path) -> str:
        digest = hashlib.sha512()

        with path.open("rb") as file:
            while True:
                chunk = file.read(1024 * 1024)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest().lower()

    def verify(self) -> bool:
        if not self.iso_path.is_file():
            return False

        print(
            f"[*] Checking SHA-512: "
            f"{self.iso_path}"
        )

        expected = self._expected_sha512()
        actual = self._sha512(self.iso_path)

        if actual == expected:
            print("[+] ISO SHA-512: OK")
            return True

        print("[ERROR] ISO SHA-512 mismatch.")
        print(f"        Expected: {expected}")
        print(f"        Actual:   {actual}")

        return False

    def ensure(self) -> Path:
        """
        Ensure that the Debian ISO exists and is valid.

        If the ISO already exists:
            verify it.

        If verification fails:
            remove it and download it again.

        If the ISO does not exist:
            download it.

        The downloaded ISO is verified before it becomes
        the final ISO path.
        """

        if self.iso_path.is_file():
            print(
                f"[*] Debian ISO found: "
                f"{self.iso_path}"
            )

            if self.verify():
                return self.iso_path

            print("[!] Existing ISO is invalid.")
            print("[*] Removing invalid ISO...")

            self.iso_path.unlink()

        else:
            print(
                f"[*] Debian ISO not found: "
                f"{self.iso_path}"
            )

        partial = self.iso_path.with_name(
            self.iso_path.name + ".part"
        )

        if partial.exists():
            print(
                f"[*] Removing incomplete download: "
                f"{partial}"
            )

            partial.unlink()

        self._download(
            self.iso_url,
            partial,
        )

        print("[*] Verifying downloaded ISO...")

        expected = self._expected_sha512()
        actual = self._sha512(partial)

        if actual != expected:
            partial.unlink(missing_ok=True)

            raise ISOError(
                "Downloaded Debian ISO failed "
                "SHA-512 verification.\n"
                f"Expected: {expected}\n"
                f"Actual:   {actual}"
            )

        partial.replace(self.iso_path)

        print(
            f"[+] Debian ISO verified: "
            f"{self.iso_path}"
        )

        return self.iso_path