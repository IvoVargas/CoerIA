"""Gera códigos em claro para distribuição e apenas hashes para o servidor."""

from __future__ import annotations

import argparse
import csv
import json
import secrets
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism.auth import credential_record


ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_code() -> str:
    groups = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join(groups)


def build_credentials(participant_count: int) -> tuple[dict, list[dict[str, str]]]:
    if participant_count < 1 or participant_count > 99:
        raise ValueError("O número de participantes deve estar entre 1 e 99.")

    plaintext: list[dict[str, str]] = []
    hashed: list[dict[str, str]] = []
    identities = [
        ("ADMIN", "Administrador", "admin"),
        *[
            (f"D{index:02d}", f"Docente {index:02d}", "participant")
            for index in range(1, participant_count + 1)
        ],
    ]
    for user_id, display_name, role in identities:
        code = generate_code()
        plaintext.append(
            {
                "user_id": user_id,
                "display_name": display_name,
                "role": role,
                "access_code": code,
            }
        )
        hashed.append(
            credential_record(
                user_id,
                display_name,
                role,
                code,
                salt=secrets.token_bytes(16),
            )
        )
    return {"version": 1, "credentials": hashed}, plaintext


def write_outputs(
    hashes_path: Path,
    codes_path: Path,
    participant_count: int,
) -> None:
    payload, plaintext = build_credentials(participant_count)
    with hashes_path.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")
    try:
        with codes_path.open("x", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=("user_id", "display_name", "role", "access_code"),
                delimiter=";",
            )
            writer.writeheader()
            writer.writerows(plaintext)
    except Exception:
        hashes_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participants", type=int, default=12)
    parser.add_argument("--hashes-out", type=Path, required=True)
    parser.add_argument("--codes-out", type=Path, required=True)
    arguments = parser.parse_args()
    write_outputs(arguments.hashes_out, arguments.codes_out, arguments.participants)


if __name__ == "__main__":
    main()
