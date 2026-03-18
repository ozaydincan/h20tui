"""
ROS 2 Window Manager TUI prototype.
A split-pane terminal UI for managing and monitoring ROS 2 processes.
Entry point into the main app.
"""

import asyncio
import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Tree

from ros2tui.ros2_entry import (build_ros_caches, fuzzy_match,
                                get_active_topics, get_workspace)
from ros2tui.ui_components import ColconMenu, ProcessPane, VimTree

if "ROS_DISTRO" not in os.environ:
    print("Error: ROS 2 environment not sourced.")
    sys.exit(1)
if "TMUX" in os.environ:
    os.environ["COLORTERM"] = "truecolor"


class ROS2TUI(App):
    """The main application containing the window manager and navigation."""

    CSS = """
    #main_container { height: 100%; }
    #sidebar { width: 30%; height: 100%; border-right: solid green; background: $surface; }
    #sidebar.hidden { display: none; }
    /* CHANGE: Target the specific search bar ID instead of all Inputs */
    #search_bar { dock: top; width: 100%; margin-bottom: 1; }
    /* NEW: Add slight spacing for inputs inside the colcon menu */
    #colcon_dialog Input { margin-bottom: 1; }
    #command_tree { width: 100%; height: 100%; }
    #command_tree:focus { border: double green; background: $surface-lighten-3; }
    #workspace { width: 1fr; height: 100%; layout: horizontal; }
    ProcessPane { width: 1fr; height: 100%; border: solid darkgray; background: $panel; }
    ProcessPane.active-pane { border: double cyan; }    .pane-title { dock: top; width: 100%; background: $surface-darken-3; color: $text; text-align: center; text-style: bold; }
ColconMenu {
        align: center middle;
    }
    #colcon_dialog {
        width: 80;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #colcon_title {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        color: $accent;
    }
    .colcon_label {
        margin-top: 1;
        text-style: bold;
        color: $text-muted;
    }
    #checkbox_row {
        height: auto;
        width: 100%;
    }
    #config_row {
        height: auto;
        width: 100%;
    }
    .config_column {
        width: 1fr;
        height: auto;
        padding-right: 1;
    }
    .colcon_buttons {
        margin-top: 2;
        align: right middle;
        height: auto;
    }
    .colcon_buttons Button {
        margin-left: 1;
    }   """

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
        Binding("ctrl+r", "refresh_workspace", "Fetch Topics"),
        ("f", "focus_search", "Search"),
        ("K", "kill_process", "Kill Active"),
        ("R", "restart_process", "Restart Active"),
        Binding("C", "colcon_menu", "Colcon Menu"),
    ]

    def __init__(self) -> None:
        """Initialize caches and window state."""
        super().__init__()
        self.active_pane: ProcessPane = ProcessPane()
        self.run_cache: dict[str, list[str]] = {}
        self.launch_cache: dict[str, list[str]] = {}
        self.cli_cache: dict[str, list[str]] = {}
        self.topic_cache: list[str] = []
        self.workspace_packages: list[str] = []

    def compose(self) -> ComposeResult:
        """Build the main UI layout."""
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
        self.run_cache, self.launch_cache, self.cli_cache = build_ros_caches()
        self.rebuild_tree()
        self.make_pane_active(self.query_one("#initial_pane", ProcessPane))
        asyncio.create_task(self.action_refresh_workspace())

    async def action_refresh_workspace(self) -> None:
        """Get topics and all the packages in the background"""
        try:
            self.notify(
                "Fetching ROS2 topics and packages", title="Searching the workspace"
            )
            self.topic_cache, self.workspace_packages = await asyncio.gather(
                get_active_topics(), get_workspace()
            )
            search_val = self.query_one("#search_bar", Input).value
            self.rebuild_tree(search_val)
            self.notify(
                f"Found {len(self.topic_cache)} topics and {len(self.workspace_packages)} packages.",
                title="Success",
            )
        except Exception as e:
            self.notify(
                f"Failed to get topics: {e}",
                title="Topic Search Error",
                severity="error",
            )

    def action_colcon_menu(self) -> None:
        """Colcon pop-up menu with build flags"""

        def execute_colcon(constructed_command: str | None) -> None:
            if not constructed_command:
                return

            if self.active_pane is None:
                self.action_new_pane()

            async def run_and_refresh() -> None:
                await self.active_pane.run_command(constructed_command)

                if self.active_pane.active_process:
                    await self.active_pane.active_process.wait()

                    if "colcon build" in constructed_command:
                        self.notify(
                            "Build complete! Updating environment...", title="Colcon"
                        )

                        ws_root = os.getcwd()
                        shell_name = os.path.basename(os.environ.get("SHELL", "bash"))

                        executable = (
                            f"/bin/{shell_name}"
                            if os.path.exists(f"/bin/{shell_name}")
                            else "/bin/bash"
                        )
                        setup_ext = (
                            shell_name
                            if os.path.exists(f"{ws_root}/install/setup.{shell_name}")
                            else "bash"
                        )

                        env_cmd = f"source {ws_root}/install/setup.{setup_ext} && env"

                        try:
                            env_proc = await asyncio.create_subprocess_shell(
                                env_cmd,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                executable=executable,
                            )
                            stdout, _ = await env_proc.communicate()

                            if env_proc.returncode == 0:
                                for line in stdout.decode().splitlines():
                                    if "=" in line:
                                        key, value = line.split("=", 1)
                                        os.environ[key] = value
                        except Exception as e:
                            self.notify(
                                f"Environment update failed: {e}", severity="warning"
                            )

                        self.run_cache, self.launch_cache, self.cli_cache = (
                            build_ros_caches()
                        )
                        search_val = self.query_one("#search_bar", Input).value
                        self.rebuild_tree(search_val)

            asyncio.create_task(run_and_refresh())

        self.push_screen(ColconMenu(self.workspace_packages), execute_colcon)

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
        self.make_pane_active(panes[max(0, idx - 1)])

    def action_pane_right(self) -> None:
        """Focus the pane to the right."""
        panes = list(self.query(ProcessPane))
        if not panes:
            return
        idx = panes.index(self.active_pane) if self.active_pane in panes else 0
        self.make_pane_active(panes[min(len(panes) - 1, idx + 1)])

    def action_toggle_sidebar(self) -> None:
        """Hides/Shows the tree to maximize view."""
        self.query_one("#sidebar").toggle_class("hidden")

    def action_kill_process(self) -> None:
        """Pass kill signal to active pane."""
        if self.active_pane is not None:
            self.active_pane.kill_process()

    async def action_restart_process(self) -> None:
        """Pass restart signal to active pane."""
        if self.active_pane is not None and self.active_pane.last_command:
            await self.active_pane.run_command(self.active_pane.last_command)

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle execution when a user selects a menu item."""
        if event.node.allow_expand or event.node.data is None:
            return
        if self.active_pane is None:
            self.action_new_pane()
        if self.active_pane is not None:
            await self.active_pane.run_command(event.node.data)
        self.query_one("#search_bar", Input).focus()

    def action_focus_search(self) -> None:
        """Hotkey to focus search bar."""
        self.query_one("#search_bar", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Trigger search filter on input."""
        self.rebuild_tree(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Transfer focus to tree on enter."""
        # type: ignore tells Pyright it's fine we aren't using the _event variable
        self.query_one("#command_tree", VimTree).focus()  # type: ignore

    def rebuild_tree(self, search_term: str = "") -> None:
        """Clear and redraw the UI Tree based on current search."""
        tree = self.query_one("#command_tree", VimTree)
        tree.clear()
        auto_expand = bool(search_term)

        self._build_run_nodes(tree.root, search_term, auto_expand)
        self._build_launch_nodes(tree.root, search_term, auto_expand)
        self._build_cli_nodes(tree.root, search_term, auto_expand)

    def _build_run_nodes(self, root_node, search_term: str, auto_expand: bool) -> None:
        """Add executable targets to the UI Tree."""
        run_node = root_node.add("ros2 run (Executables)", expand=True)
        for pkg, execs in self.run_cache.items():
            matching_execs = [
                ex for ex in execs if fuzzy_match(search_term, f"{pkg} {ex}")
            ]
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
            matching_files = [
                lf for lf in files if fuzzy_match(search_term, f"{pkg} {lf}")
            ]
            if matching_files:
                pkg_node = launch_node.add(pkg, expand=auto_expand)
                for lf in matching_files:
                    pkg_node.add_leaf(lf, data=f"ros2 launch {pkg} {lf}")

    def _build_cli_nodes(self, root_node, search_term: str, auto_expand: bool) -> None:
        """Add CLI verb targets to the UI Tree."""
        cli_node = root_node.add("CLI Commands", expand=True)
        for cmd, verbs in self.cli_cache.items():
            if verbs:
                cmd_node = None

                for v in verbs:
                    if cmd == "topic":
                        allowed_topic_verbs = [
                            "echo",
                            "hz",
                            "info",
                            "bw",
                            "delay",
                            "type",
                        ]

                        if v not in allowed_topic_verbs:
                            continue

                        topics = getattr(self, "topic_cache", [])

                        matching_topics = [
                            t
                            for t in topics
                            if fuzzy_match(search_term, f"{cmd} {v} {t}")
                        ]

                        if fuzzy_match(search_term, f"{cmd} {v}"):
                            topics_to_show = topics
                        else:
                            topics_to_show = matching_topics

                        if topics_to_show:
                            if cmd_node is None:
                                cmd_node = cli_node.add(cmd, expand=auto_expand)

                            verb_node = cmd_node.add(v, expand=auto_expand)
                            for t in topics_to_show:
                                verb_node.add_leaf(t, data=f"ros2 {cmd} {v} {t}")

                    # 4. Standard CLI Commands (like node, param, service, etc.)
                    else:
                        if fuzzy_match(search_term, f"{cmd} {v}"):
                            if cmd_node is None:
                                cmd_node = cli_node.add(cmd, expand=auto_expand)
                            cmd_node.add_leaf(v, data=f"ros2 {cmd} {v}")
            else:
                if fuzzy_match(search_term, cmd):
                    cli_node.add(cmd, expand=auto_expand).add_leaf(
                        "<base command>", data=f"ros2 {cmd}"
                    )


def main() -> None:
    """
    Entry point of the app
    """

    app = ROS2TUI()
    app.run()


if __name__ == "__main__":
    main()
