"""
ROS 2 Window Manager TUI prototype.
A split-pane terminal UI for managing and monitoring ROS 2 processes.
"""

import asyncio
import os
import signal
import sys

from ament_index_python.packages import (get_package_share_directory,
                                         get_packages_with_prefixes)
from rich.text import Text
from ros2cli.command import get_command_extensions
from ros2cli.entry_points import get_entry_points
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, RichLog, Tree

# Ensure ROS 2 is sourced before running
if "ROS_DISTRO" not in os.environ:
    print("Error: ROS 2 environment not sourced.")
    sys.exit(1)

# Tmux compatibility fix for colors
if "TMUX" in os.environ:
    os.environ["COLORTERM"] = "truecolor"


def fuzzy_match(query: str, text: str) -> bool:
    """A lightweight fuzzy matching algorithm similar to fzf."""
    if not query:
        return True
    query = query.lower()
    text = text.lower()
    query_idx = 0
    for char in text:
        if query_idx < len(query) and char == query[query_idx]:
            query_idx += 1
        if query_idx == len(query):
            return True
    return False


# --- Custom Vim-Enabled Widgets ---


class VimTree(Tree):
    """A Tree widget with Vim-style hjkl navigation."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "cursor_left", "Left", show=False),
        Binding("l", "cursor_right", "Right", show=False),
    ]


class VimLog(RichLog):
    """A RichLog with Vim-style hjkl scrolling."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("h", "scroll_left", "Scroll Left", show=False),
        Binding("l", "scroll_right", "Scroll Right", show=False),
    ]


# --- Process Window Manager Pane ---


class ProcessPane(Vertical, can_focus=True):
    """An independent container that manages its own subprocess and log."""

    def __init__(self, **kwargs) -> None:
        """Initialize the pane with empty process trackers."""
        super().__init__(**kwargs)
        self.active_process = None
        self.last_command: str | None = None

    def compose(self) -> ComposeResult:
        """Render the pane UI layout."""
        yield Label("Idle", classes="pane-title")
        yield VimLog(highlight=True, markup=False)

    def on_click(self, _event: events.Click) -> None:
        """Clicking anywhere on the pane makes it the active target."""
        self.app.make_pane_active(self)  # type: ignore

    async def run_command(self, cmd: str) -> None:
        """Executes a ROS 2 command inside this pane's subprocess."""
        if self.active_process is not None:
            self.kill_process()

        self.last_command = cmd
        self.query_one(Label).update(f"Running: {cmd}")

        log = self.query_one(VimLog)
        log.clear()

        start_text = Text(f"--- Starting: {cmd} ---", style="bold green")
        log.write(start_text)

        self.active_process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        async def read_stream(stream, is_error=False):
            """Reads an async stream and pushes it to the log."""
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded_line = line.decode().rstrip()
                out_text = Text(decoded_line)
                if is_error:
                    out_text.stylize("bold red")
                log.write(out_text)

        if self.active_process.stdout:
            asyncio.create_task(read_stream(self.active_process.stdout))
        if self.active_process.stderr:
            asyncio.create_task(read_stream(self.active_process.stderr, is_error=True))

    def kill_process(self) -> None:
        """Terminates the process group running in this pane."""
        if self.active_process is not None:
            try:
                os.killpg(os.getpgid(self.active_process.pid), signal.SIGTERM)
                log = self.query_one(VimLog)
                log.write(Text("\n--- Process Group Terminated ---", style="bold red"))
                self.query_one(Label).update(f"Killed: {self.last_command}")
                self.active_process = None
            except ProcessLookupError:
                pass

    def clear_log(self) -> None:
        """Clears the terminal output log."""
        self.query_one(VimLog).clear()


# --- Main Application ---


class ROS2TUI(App):
    """The main application containing the window manager and navigation."""

    CSS = """
    #main_container {
        height: 100%;
    }
    #sidebar {
        width: 30%;
        height: 100%;
        border-right: solid green;
        background: $surface;
    }
    #sidebar.hidden {
        display: none;
    }
    Input {
        dock: top;
        width: 100%;
        margin-bottom: 1;
    }
    #command_tree {
        width: 100%;
        height: 100%;
    }
    #command_tree:focus {
        border: double green;
        background: $surface-lighten-3;
    }
    #workspace {
        width: 1fr;
        height: 100%;
        layout: horizontal;
    }
    
    /* Process Pane Styling */
    ProcessPane {
        width: 1fr;
        height: 100%;
        border: solid darkgray;
        background: $panel;
    }
    ProcessPane.active-pane {
        border: double cyan;
    }
    .pane-title {
        dock: top;
        width: 100%;
        background: $surface-darken-3;
        color: $text;
        text-align: center;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        Binding("b", "toggle_sidebar", "Toggle Menu"),
        Binding("ctrl+b", "toggle_sidebar", show=False),
        ("n", "new_pane", "New Pane"),
        ("x", "close_pane", "Close Pane"),
        Binding("ctrl+h", "pane_left", "Left Pane"),
        Binding("ctrl+l", "pane_right", "Right Pane"),
        Binding("ctrl+j", "pane_right", show=False),
        Binding("ctrl+k", "pane_left", show=False),
        ("f", "focus_search", "Search"),
        ("K", "kill_process", "Kill Active"),
        ("R", "restart_process", "Restart Active"),
    ]

    def __init__(self) -> None:
        """Initialize caches and state."""
        super().__init__()
        self.active_pane: ProcessPane | None = None
        self.run_cache: dict[str, list[str]] = {}
        self.launch_cache: dict[str, list[str]] = {}
        self.cli_cache: dict[str, list[str]] = {}

    def compose(self) -> ComposeResult:
        """Build the main UI tree."""
        yield Header(show_clock=True)
        with Horizontal(id="main_container"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="Fuzzy find (Press Enter)...", id="search_bar")
                yield VimTree("ROS 2 Environment", id="command_tree")
            with Horizontal(id="workspace"):
                yield ProcessPane(id="initial_pane")
        yield Footer()

    def on_mount(self) -> None:
        """Populate ROS 2 data and set up initial state."""
        self.populate_caches()
        self.rebuild_tree()
        self.make_pane_active(self.query_one("#initial_pane", ProcessPane))

    # --- Window Manager Logic ---

    def make_pane_active(self, target_pane: ProcessPane) -> None:
        """Highlights the targeted pane so commands route to it."""
        for pane in self.query(ProcessPane):
            pane.remove_class("active-pane")
        target_pane.add_class("active-pane")
        self.active_pane = target_pane

    def action_new_pane(self) -> None:
        """Splits the workspace by adding a new terminal pane."""
        new_pane = ProcessPane()
        self.query_one("#workspace").mount(new_pane)
        self.make_pane_active(new_pane)

    def action_close_pane(self) -> None:
        """Kills process and removes active pane."""
        panes = list(self.query(ProcessPane))
        if len(panes) > 1 and self.active_pane is not None:
            self.active_pane.kill_process()
            self.active_pane.remove()
            self.make_pane_active(list(self.query(ProcessPane))[0])

    def action_pane_left(self) -> None:
        """Focus the pane to the left."""
        panes = list(self.query(ProcessPane))
        if not panes:
            return
        idx = panes.index(self.active_pane) if self.active_pane in panes else 0
        prev_idx = max(0, idx - 1)
        self.make_pane_active(panes[prev_idx])

    def action_pane_right(self) -> None:
        """Focus the pane to the right."""
        panes = list(self.query(ProcessPane))
        if not panes:
            return
        idx = panes.index(self.active_pane) if self.active_pane in panes else 0
        next_idx = min(len(panes) - 1, idx + 1)
        self.make_pane_active(panes[next_idx])

    def action_toggle_sidebar(self) -> None:
        """Hides/Shows the tree to maximize view."""
        sidebar = self.query_one("#sidebar")
        sidebar.toggle_class("hidden")

    # --- Pass-through Actions to Active Pane ---

    def action_kill_process(self) -> None:
        """Pass kill signal to active pane."""
        if self.active_pane is not None:
            self.active_pane.kill_process()

    async def action_restart_process(self) -> None:
        """Pass restart signal to active pane."""
        if self.active_pane is not None and self.active_pane.last_command:
            await self.active_pane.run_command(self.active_pane.last_command)

    def action_clear_log(self) -> None:
        """Pass clear log signal to active pane."""
        if self.active_pane is not None:
            self.active_pane.clear_log()

    # --- Tree Execution & Build ---

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle execution when a user selects a menu item."""
        if event.node.allow_expand or event.node.data is None:
            return

        cmd = event.node.data
        if self.active_pane is None:
            self.action_new_pane()

        if self.active_pane is not None:
            await self.active_pane.run_command(cmd)

        self.query_one("#search_bar", Input).focus()

    def action_focus_search(self) -> None:
        """Hotkey to focus search bar."""
        self.query_one("#search_bar", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Trigger search filter on input."""
        self.rebuild_tree(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Transfer focus to tree on enter."""
        self.query_one("#command_tree", VimTree).focus()

    # --- Caching and Tree Building Helpers ---

    def populate_caches(self) -> None:
        """Main entry point to build internal ROS 2 caches."""
        try:
            packages = get_packages_with_prefixes()
        except Exception:  # pylint: disable=broad-exception-caught
            packages = {}

        for pkg, prefix in sorted(packages.items()):
            self._cache_executables(pkg, prefix)
            self._cache_launch_files(pkg)

        self._cache_cli_commands()

    def _cache_executables(self, pkg: str, prefix: str) -> None:
        """Scan and cache package executables."""
        lib_path = os.path.join(prefix, "lib", pkg)
        if os.path.isdir(lib_path):
            execs = [
                f
                for f in os.listdir(lib_path)
                if os.path.isfile(os.path.join(lib_path, f))
                and os.access(os.path.join(lib_path, f), os.X_OK)
            ]
            if execs:
                self.run_cache[pkg] = sorted(execs)

    def _cache_launch_files(self, pkg: str) -> None:
        """Scan and cache package launch files."""
        try:
            share_path = get_package_share_directory(pkg)
            launch_files = []
            for _, _, files in os.walk(share_path):
                for f in files:
                    if f.endswith(("launch.py", "launch.xml", "launch.yaml")):
                        launch_files.append(f)
            if launch_files:
                self.launch_cache[pkg] = sorted(launch_files)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _cache_cli_commands(self) -> None:
        """Scan and cache dynamic ROS 2 CLI commands."""
        try:
            command_extensions = get_command_extensions("ros2cli.command")
            for cmd_name in sorted(command_extensions.keys()):
                if cmd_name in ["run", "launch"]:
                    continue
                verb_group = f"ros2{cmd_name}.verb"
                try:
                    verbs = get_entry_points(verb_group)
                    if verbs:
                        self.cli_cache[cmd_name] = sorted(verbs.keys())
                    else:
                        self.cli_cache[cmd_name] = []
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def rebuild_tree(self, search_term: str = "") -> None:
        """Clear and redraw the UI Tree based on current search."""
        tree = self.query_one("#command_tree", VimTree)
        tree.clear()
        auto_expand = bool(search_term)

        self._build_run_nodes(tree.root, search_term, auto_expand)
        self._build_launch_nodes(tree.root, search_term, auto_expand)
        self._build_cli_nodes(tree.root, search_term, auto_expand)

        if not search_term:
            monitor_node = tree.root.add("Topic Monitoring", expand=True)
            monitor_node.add_leaf("topic list -t", data="ros2 topic list -t")
            monitor_node.add_leaf("topic hz /rosout", data="ros2 topic hz /rosout")
            monitor_node.add_leaf("topic echo /rosout", data="ros2 topic echo /rosout")

    def _build_run_nodes(self, root_node, search_term: str, auto_expand: bool) -> None:
        """Add executable targets to the UI Tree."""
        run_node = root_node.add("ros2 run (Executables)", expand=True)
        for pkg, execs in self.run_cache.items():
            # Check the combined "package_name executable_name" string
            matching_execs = [
                ex for ex in execs if fuzzy_match(search_term, f"{pkg} {ex}")
            ]

            # Only add the package folder if it contains matching executables
            if matching_execs:
                pkg_node = run_node.add(pkg, expand=auto_expand)
                for ex in matching_execs:
                    pkg_node.add_leaf(ex, data=f"ros2 run {pkg} {ex}")

    def _build_launch_nodes(
        self, root_node, search_term: str, auto_expand: bool
    ) -> None:
        """Add launch file targets to the UI Tree."""
        launch_node = root_node.add("ros2 launch (Launch Files)", expand=True)
        for pkg, files in self.launch_cache.items():
            # Check the combined "package_name launch_file_name" string
            matching_files = [
                lf for lf in files if fuzzy_match(search_term, f"{pkg} {lf}")
            ]

            # Only add the package folder if it contains matching launch files
            if matching_files:
                pkg_node = launch_node.add(pkg, expand=auto_expand)
                for lf in matching_files:
                    pkg_node.add_leaf(lf, data=f"ros2 launch {pkg} {lf}")

    def _build_cli_nodes(self, root_node, search_term: str, auto_expand: bool) -> None:
        """Add CLI verb targets to the UI Tree."""
        cli_node = root_node.add("CLI Commands", expand=True)
        for cmd, verbs in self.cli_cache.items():
            if verbs:
                # Check the combined "command verb" string (e.g., "topic list")
                matching_verbs = [
                    verb for verb in verbs if fuzzy_match(search_term, f"{cmd} {verb}")
                ]

                if matching_verbs:
                    cmd_node = cli_node.add(cmd, expand=auto_expand)
                    for verb in matching_verbs:
                        cmd_node.add_leaf(verb, data=f"ros2 {cmd} {verb} --help")
            else:
                # If a base command has no verbs, just match against the command name
                if fuzzy_match(search_term, cmd):
                    cmd_node = cli_node.add(cmd, expand=auto_expand)
                    cmd_node.add_leaf("<base command>", data=f"ros2 {cmd} --help")


if __name__ == "__main__":
    app = ROS2TUI()
    app.run()
