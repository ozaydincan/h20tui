"""
ROS 2 Window Manager TUI prototype.
A split-pane terminal UI for managing and monitoring ROS 2 processes.
Entry point into the main app.
"""

import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Tree

from .ros2_entry import build_ros_caches, fuzzy_match
from .ui_components import ProcessPane, VimTree

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
    Input { dock: top; width: 100%; margin-bottom: 1; }
    #command_tree { width: 100%; height: 100%; }
    #command_tree:focus { border: double green; background: $surface-lighten-3; }
    #workspace { width: 1fr; height: 100%; layout: horizontal; }
    ProcessPane { width: 1fr; height: 100%; border: solid darkgray; background: $panel; }
    ProcessPane.active-pane { border: double cyan; }
    .pane-title { dock: top; width: 100%; background: $surface-darken-3; color: $text; text-align: center; text-style: bold; }
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
        """Initialize caches and window state."""
        super().__init__()
        self.active_pane: ProcessPane | None = None
        self.run_cache: dict[str, list[str]] = {}
        self.launch_cache: dict[str, list[str]] = {}
        self.cli_cache: dict[str, list[str]] = {}

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

        if not search_term:
            monitor_node = tree.root.add("Topic Monitoring", expand=True)
            monitor_node.add_leaf("topic list -t", data="ros2 topic list -t")
            monitor_node.add_leaf("topic echo /rosout", data="ros2 topic echo /rosout")

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
                matching_verbs = [
                    v for v in verbs if fuzzy_match(search_term, f"{cmd} {v}")
                ]
                if matching_verbs:
                    cmd_node = cli_node.add(cmd, expand=auto_expand)
                    for v in matching_verbs:
                        cmd_node.add_leaf(v, data=f"ros2 {cmd} {v} --help")
            else:
                if fuzzy_match(search_term, cmd):
                    cmd_node = cli_node.add(cmd, expand=auto_expand)
                    cmd_node.add_leaf("<base command>", data=f"ros2 {cmd} --help")


if __name__ == "__main__":
    app = ROS2TUI()
    app.run()
