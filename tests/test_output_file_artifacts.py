"""
Checks output-file artifact parsing boundaries.

Usage:
    python tests/test_output_file_artifacts.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.output_file_artifacts import (
    extract_output_file_path_from_tool_calls,
    extract_path_from_text,
    looks_like_file_status,
)


def test_output_file_artifact_parser_boundary() -> None:
    created_path = r"C:\Users\SAI\Desktop\bill_gates_net_worth.md"

    assert (
        extract_output_file_path_from_tool_calls(
            [
                {
                    "tool_name": "read_file",
                    "parameters": {"file_path": r"C:\Users\SAI\Desktop\notes.txt"},
                    "status": "success",
                },
                {
                    "tool_name": "write_file",
                    "parameters": {"file_path": created_path},
                    "status": "success",
                },
            ]
        )
        == created_path
    )

    assert (
        extract_output_file_path_from_tool_calls(
            [
                {
                    "tool_name": "write_file",
                    "parameters": {"file_path": created_path},
                    "status": "error",
                }
            ]
        )
        == ""
    )

    assert extract_path_from_text(f"Created file: `{created_path}`.") == created_path
    assert looks_like_file_status(f"The answer has been written to {created_path}.")
    assert not looks_like_file_status("Bill Gates net worth is about $120 billion.")


if __name__ == "__main__":
    test_output_file_artifact_parser_boundary()
    print("[test_output_file_artifacts] All checks passed.")
