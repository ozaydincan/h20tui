"""
Custom Textual UI components for the ROS 2 Window Manager TUI.
Includes Vim-style navigation widgets and the isolated ProcessPane.
"""

import asyncio
import os
import signal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import (Button, Checkbox, Input, Label, RichLog, Select,
                             Tree)


class SuggestionCycler(Input):
    """Custom input class for package name suggestions"""

    def __init__(self, pkgs: list[str], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pkgs = sorted(pkgs)
        self.cycle_matches: list[str] = []
        self.cycle_index = -1
        self.base_prefix = ""

    def on_key(self, event: events.Key) -> None:
        """Cycle through using up and dow keys"""
        if event.key in ("up", "down"):
            event.prevent_default()
            if not self.cycle_matches:
                prefix, space, curr_word = self.value.rpartition(" ")
                self.base_prefix = prefix + space
                s_word = curr_word.lower()
                self.cycle_matches = [
                    pkg for pkg in self.pkgs if pkg.lower().startswith(s_word)
                ]
                if not self.cycle_matches:
                    self.notify("No matches!", severity="warning")
                    return
                self.cycle_index = (
                    0 if event.key == "down" else len(self.cycle_matches) - 1
                )
            if event.key == "down":
                self.cycle_index -= 1
            elif event.key == "up":
                self.cycle_index += 1
            self.cycle_index %= len(self.cycle_matches)
            self.value = self.base_prefix + self.cycle_matches[self.cycle_index]
            self.cursor_position = len(self.value)
        elif event.is_printable or event.key in ("backspace", "delete", "space"):
            self.cycle_index = -1
            self.cycle_matches = []


class MultiTokenSuggester(Suggester):
    """Extending Textual Suggester for multiple package names"""

    def __init__(self, options: list[str], case_sensitive: bool = False):
        super().__init__(use_cache=False)
        self.options = options
        self.case_sensitive = case_sensitive

    async def get_suggestion(self, value: str) -> str | None:
        value_strip = value.strip()
        if not value_strip or value.isspace():
            return
        words = value_strip.split()
        if not words:
            return
        curr_word = words[-1]
        search_word = curr_word if self.case_sensitive else curr_word.lower()

        for option in self.options:
            compare_opt = option if self.case_sensitive else option.lower()
            if compare_opt.startswith(search_word):
                return value[: -len(curr_word)] + option
        return None


class ColconMenu(ModalScreen[str]):
    """A pop-up menu for constructing complex colcon commands."""

    def __init__(self, workspace_packages: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.workspace_packages = workspace_packages
        self.pkg_suggester = MultiTokenSuggester(
            self.workspace_packages, case_sensitive=False
        )

    BINDINGS = [
        Binding("escape", "cancel_menu", "Cancel", show=True),
        Binding("ctrl+enter", "run_colcon", "Run Command", show=True),
    ]

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
                SuggestionCycler(
                    pkgs=self.workspace_packages,
                    placeholder="pkg1 pkg2",
                    id="packages_select",
                ),
                SuggestionCycler(
                    pkgs=self.workspace_packages,
                    placeholder="pkg1 pkg2",
                    id="packages_up_to",
                ),
                Label("Packages Skip Regex:"),
                SuggestionCycler(
                    pkgs=self.workspace_packages,
                    placeholder="skip building packages with regex",
                    id="packages_skip_regex",
                ),
                Label("Packages Select Regex:"),
                SuggestionCycler(
                    pkgs=self.workspace_packages,
                    placeholder="select packages with regex",
                    id="packages_select_regex",
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
                        Label("Parallel Workers (enter a value to trigger):"),
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
        "Physical button click support"
        if event.button.id == "cancel_colcon":
            self.dismiss(None)

        elif event.button.id == "run_colcon":
            self.action_run_colcon()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Enable flags only for dynamic actions"""
        if event.select.id == "colcon_verb":
            is_dynamic = event.value in ["build", "test"]
            build_flags = [
                "#symlink_install",
                "#continue_on_error",
                "#cmake_clean",
                "#parallel_workers",
                "#cmake_build_type",
                "#source_workspace",
            ]
            for flag_id in build_flags:
                self.query_one(flag_id).disabled = not is_dynamic

    def action_cancel_menu(self) -> None:
        """Dismiss the menu without returning a command."""
        self.dismiss(None)

    def action_run_colcon(self) -> None:
        """Construct and execute the colcon command."""
        verb = self.query_one("#colcon_verb", Select).value
        cmd = f"colcon {verb}"

        pkg_sel = self.query_one("#packages_select", Input).value.strip()
        if pkg_sel:
            cmd += f" --packages-select {pkg_sel}"

        pkg_up_to = self.query_one("#packages_up_to", Input).value.strip()
        if pkg_up_to:
            cmd += f" --packages-up-to {pkg_up_to}"

        pkg_skip_regex = self.query_one("#packages_skip_regex", Input).value.strip()
        if pkg_skip_regex:
            cmd += f" --packages-skip-regex {pkg_skip_regex}"

        pkg_sel_regex = self.query_one("#packages_select_regex", Input).value.strip()
        if pkg_sel_regex:
            cmd += f" --packages-select-regex {pkg_sel_regex}"

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

        if self.query_one("#source_workspace", Checkbox).value:
            shell_name = os.path.basename(os.environ.get("SHELL", "bash"))
            setup_file = f"install/setup.{shell_name}"
            cmd += f" && test -f {setup_file} && source {setup_file} || true"

        self.dismiss(cmd)


class VimTree(Tree):
    """A Tree widget mapped with Vim-style hjkl navigation bindings."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "cursor_left", "Left", show=False),
        Binding("l", "cursor_right", "Right", show=False),
    ]


class VimLog(RichLog):
    """A RichLog widget mapped with Vim-style hjkl scrolling bindings."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("h", "scroll_left", "Scroll Left", show=False),
        Binding("l", "scroll_right", "Scroll Right", show=False),
    ]


class ProcessPane(Vertical, can_focus=True):
    """An independent vertical container that manages its own subprocess and log."""

    def __init__(self, **kwargs) -> None:
        """Initialize the pane with empty process trackers."""
        super().__init__(**kwargs)
        self.active_process = None
        self.last_command: str | None = None

    def compose(self) -> ComposeResult:
        """Render the pane UI layout."""
        yield Label("Ready", classes="pane-title")
        yield VimLog(highlight=True, markup=False)

    def on_click(self, event: events.Click) -> None:
        """Make this pane active when clicked."""
        _ = event  # Silence Pyright unused variable warning
        self.app.make_pane_active(self)  # type: ignore

    async def run_command(self, cmd: str) -> None:
        """Execute a ROS 2 command inside this pane's subprocess."""
        if self.active_process is not None:
            self.kill_process()

        self.last_command = cmd
        ws_root = os.getcwd()
        self.query_one(Label).update(f"Running: {cmd}")
        log = self.query_one(VimLog)
        log.clear()
        log.write(Text(f"--- Starting: {cmd} ---", style="bold green"))
        shell_exec = os.environ.get("SHELL", "/bin/bash")
        self.active_process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,
            cwd=ws_root,
            executable=shell_exec,
        )

        async def read_stream(stream, is_error=False):
            """Read from async stream and write to the log widget."""
            while True:
                line = await stream.readline()
                if not line:
                    break
                out_text = Text(line.decode().rstrip())
                if is_error:
                    out_text.stylize("bold red")
                log.write(out_text)

        if self.active_process.stdout:
            asyncio.create_task(read_stream(self.active_process.stdout))
        if self.active_process.stderr:
            asyncio.create_task(read_stream(self.active_process.stderr, is_error=True))

    def kill_process(self) -> None:
        """Terminate the process group running in this pane."""
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
        """Clear the terminal output log of this pane."""
        self.query_one(VimLog).clear()
