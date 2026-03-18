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
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import (Button, Checkbox, Footer, Header, Input, Label,
                             Select, Tree)

from ros2tui.ros2_entry import (build_ros_caches, fuzzy_match,
                                get_active_topics, get_workspace)
from ros2tui.ui_components import ProcessPane, VimTree

if "ROS_DISTRO" not in os.environ:
    print("Error: ROS 2 environment not sourced.")
    sys.exit(1)
if "TMUX" in os.environ:
    os.environ["COLORTERM"] = "truecolor"


class ColconMenu(ModalScreen[str]):
    """A pop-up menu for constructing complex colcon commands."""

    def __init__(self, workspace_packages: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.workspace_packages = workspace_packages
        self.pkg_suggester = SuggestFromList(
            self.workspace_packages, case_sensitive=False
        )

    def compose(self) -> ComposeResult:
        verbs = [
            (v, v) for v in ["build", "test", "test-result", "list", "graph", "info"]
        ]
        build_types = [
            ("None (Default)", ""),
            ("Release", "Release"),
            ("Debug", "Debug"),
            ("RelWithDebInfo", "RelWithDebInfo"),
        ]

        yield Grid(
            Label("Colcon Commands", id="colcon_title"),
            VerticalScroll(
                Label("Verb:"),
                Select(verbs, value="build", id="colcon_verb"),
                Label("Package Selection (space separated):"),
                Input(
                    placeholder="--packages-select pkg1 pkg2...",
                    id="packages_select",
                    suggester=self.pkg_suggester,
                ),
                Input(
                    placeholder="--packages-up-to pkg1 pkg2...",
                    id="packages_up_to",
                    suggester=self.pkg_suggester,
                ),
                Label("Common Build Flags:"),
                Horizontal(
                    Checkbox("Symlink Install", id="symlink_install", value=True),
                    Checkbox("Continue on Error", id="continue_on_error"),
                    Checkbox("CMake Clean Cache", id="cmake_clean"),
                    id="checkbox_row",
                ),
                Label("Build Configuration:"),
                Horizontal(
                    Vertical(
                        Label("Parallel Workers:"),
                        Input(
                            placeholder="e.g. 4 or $(nproc)",
                            id="parallel_workers",
                        ),
                        classes="config_column",
                    ),
                    Vertical(
                        Label("CMake Build Type:"),
                        Select(build_types, value="", id="cmake_build_type"),
                        classes="config_column",
                    ),
                    id="config_row",
                ),
                Label("Additional CMake Args:"),
                Input(placeholder="-DBUILD_TESTING=OFF ...", id="cmake_args"),
                Label("Extra Colcon Arguments:"),
                Input(placeholder="Any other flags...", id="extra_args"),
                Label("Post-Build Actions:"),
                Checkbox(
                    "Source workspace after build", id="source_workspace", value=True
                ),
                Horizontal(
                    Button("Run Command", variant="success", id="run_colcon"),
                    Button("Cancel", variant="error", id="cancel_colcon"),
                    classes="colcon_buttons",
                ),
            ),
            id="colcon_dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel_colcon":
            self.dismiss(None)

        elif event.button.id == "run_colcon":
            verb = self.query_one("#colcon_verb", Select).value
            cmd = f"colcon {verb}"

            pkg_sel = self.query_one("#packages_select", Input).value.strip()
            if pkg_sel:
                cmd += f" --packages-select {pkg_sel}"

            pkg_up_to = self.query_one("#packages_up_to", Input).value.strip()
            if pkg_up_to:
                cmd += f" --packages-up-to {pkg_up_to}"

            if verb in ["build", "test"]:
                if self.query_one("#symlink_install", Checkbox).value:
                    cmd += " --symlink-install"
                if self.query_one("#continue_on_error", Checkbox).value:
                    cmd += " --continue-on-error"
                if self.query_one("#cmake_clean", Checkbox).value:
                    cmd += " --cmake-clean-cache"

            workers = self.query_one("#parallel_workers", Input).value.strip()
            if workers:
                cmd += f" --parallel-workers {workers}"

            cmake_args_list = []

            build_type = self.query_one("#cmake_build_type", Select).value
            if build_type and build_type != Select.BLANK:
                cmake_args_list.append(f"-DCMAKE_BUILD_TYPE={build_type}")

            additional_cmake = self.query_one("#cmake_args", Input).value.strip()
            if additional_cmake:
                cmake_args_list.append(additional_cmake)

            if cmake_args_list:
                cmd += " --cmake-args " + " ".join(cmake_args_list)

            extra = self.query_one("#extra_args", Input).value.strip()
            if extra:
                cmd += f" {extra}"

            if self.query_one("#source_workspace", Checkbox).value:
                shell_name = os.path.basename(os.environ.get("SHELL", "bash"))
                cmd += f" && source install/setup.{shell_name}"

            self.dismiss(cmd)


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
        Binding("ctrl+r", "refresh_topics", "Fetch Topics"),
        ("f", "focus_search", "Search"),
        ("K", "kill_process", "Kill Active"),
        ("R", "restart_process", "Restart Active"),
        Binding("C", "colcon_menu", "Colcon Menu"),
    ]

    def __init__(self) -> None:
        """Initialize caches and window state."""
        super().__init__()
        self.active_pane: ProcessPane | None = None
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
