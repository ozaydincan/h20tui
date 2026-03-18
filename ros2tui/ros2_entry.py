"""
Handles the data and the ROS 2 logic
"""

import asyncio
import os

from ament_index_python.packages import (get_package_share_directory,
                                         get_packages_with_prefixes)
from ros2cli.command import get_command_extensions
from ros2cli.entry_points import get_entry_points


def fuzzy_match(query: str, text: str) -> bool:
    """A lightweight fuzzy matching algorithm."""
    if not query:
        return True
    query, text = query.lower(), text.lower()
    query_idx = 0
    for char in text:
        if query_idx < len(query) and char == query[query_idx]:
            query_idx += 1
        if query_idx == len(query):
            return True
    return False


def _cache_executables(pkg: str, prefix: str, run_cache: dict) -> None:
    """Helper to find and cache ROS 2 executables for a package."""
    lib_path = os.path.join(prefix, "lib", pkg)
    if os.path.isdir(lib_path):
        execs = [
            f
            for f in os.listdir(lib_path)
            if os.path.isfile(os.path.join(lib_path, f))
            and os.access(os.path.join(lib_path, f), os.X_OK)
        ]
        if execs:
            run_cache[pkg] = sorted(execs)


def _cache_launch_files(pkg: str, launch_cache: dict) -> None:
    """Helper to find and cache ROS 2 launch files for a package."""
    try:
        share_path = get_package_share_directory(pkg)
        launch_files = []
        for _, _, files in os.walk(share_path):
            for f in files:
                if f.endswith(("launch.py", "launch.xml", "launch.yaml")):
                    launch_files.append(f)
        if launch_files:
            launch_cache[pkg] = sorted(launch_files)
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def _cache_cli_commands(cli_cache: dict) -> None:
    """Helper to find and cache ROS 2 CLI commands and their verbs."""
    try:
        command_extensions = get_command_extensions("ros2cli.command")
        for cmd_name in sorted(command_extensions.keys()):
            if cmd_name in ["run", "launch"]:
                continue
            verb_group = f"ros2{cmd_name}.verb"
            try:
                verbs = get_entry_points(verb_group)
                cli_cache[cmd_name] = sorted(verbs.keys()) if verbs else []
            except Exception:  # pylint: disable=broad-exception-caught
                pass
    except Exception:  # pylint: disable=broad-exception-caught
        pass


async def get_active_topics() -> list[str]:
    """
    Get the active topic names running
    """
    process = await asyncio.create_subprocess_shell(
        "ros2 topic list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    topics, _err = await process.communicate()

    if process.returncode == 0:
        return [line.strip() for line in topics.decode().split("\n") if line.strip()]
    return ["Topic name parsing failed"]

async def get_workspace() -> list[str]:
    """Get the built and unbuilt packages in the ws"""
    process = await asyncio.create_subprocess_shell(
                "colcon list --names-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
    stdout, _ = await process.communicate()
            
    if process.returncode == 0:
        return [line.strip() for line in stdout.decode().split('\n') if line.strip()]
    return ["Problem getting packages"]

def build_ros_caches() -> tuple[dict, dict, dict]:
    """Scans the ROS 2 environment and returns run, launch, and cli caches."""
    run_cache: dict = {}
    launch_cache: dict = {}
    cli_cache: dict = {}

    try:
        packages = get_packages_with_prefixes()
    except Exception:  # pylint: disable=broad-exception-caught
        packages = {}

    for pkg, prefix in sorted(packages.items()):
        _cache_executables(pkg, prefix, run_cache)
        _cache_launch_files(pkg, launch_cache)

    _cache_cli_commands(cli_cache)

    return run_cache, launch_cache, cli_cache
