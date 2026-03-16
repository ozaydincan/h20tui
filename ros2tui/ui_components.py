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
from textual.containers import Vertical
from textual.widgets import Label, RichLog, Tree


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
        yield Label("Idle", classes="pane-title")
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
        self.query_one(Label).update(f"Running: {cmd}")
        log = self.query_one(VimLog)
        log.clear()
        log.write(Text(f"--- Starting: {cmd} ---", style="bold green"))

        self.active_process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,
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
