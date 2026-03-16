# ROS 2 Window Manager TUI (h20tui)

A high-performance, asynchronous Text User Interface (TUI) designed for **ROS 2 Humble**. This tool transforms your terminal into a tiling window manager specifically tuned for robotics development. Navigate your workspace, monitor topics, and manage multiple nodes side-by-side using pure keyboard motions.

---

## 🚀 Key Features

- **Ament-Aware Fuzzy Discovery:** Instantly find executables and launch files by scanning the `ament_index`. No more "trash" suggestions from standard bash completion.
- **Tiling Workspace:** Split your view into multiple independent panes to monitor `topic echo`, `node info`, and `launch` logs simultaneously.
- **Vim-Powered Navigation:** Full `hjkl` support for tree navigation, log scrolling, and `Ctrl + h/l` for lightning-fast pane switching.
- **Robust Process Management:** Uses Unix process groups (`os.killpg`) to ensure that killing a `ros2 launch` command actually cleans up all child nodes.
- **Search-to-Select Workflow:** Seamless focus transition from the fuzzy-search bar to the command tree using only the `Enter` key.

---

## 📦 Installation

### Prerequisites

- Ubuntu 22.04
- ROS 2 Humble (Sourced)
- Python 3.10+

### 1. From Source

To install in "editable" mode so that changes to the code take effect immediately:

```bash
git clone git@github.com:ozaydincan/h20tui.git 
cd h20tui
pip install -e .
```

### 2. From Pip (Recommended)

You can install **h20tui** directly from PyPI:

```bash
pip install h20tui
source /opt/ros/humble/setup.bash
# (Optional) Source your workspace
source ~/your_ws/install/setup.bash
```

## Running the TUI

If ROS2 is sourced in your workspace

```bash
ros2tui
```


