"""
Setup configuration for the h20tui package.
"""
with open("README.md", encoding="utf-8") as f:
    long_desc = f.read()

from setuptools import find_packages, setup

setup(
    name="h20tui",
    version="1.0.0",
    description="A tiling window manager TUI for ROS 2 Humble",
    author="Can Ozaydin",
    long_description=long_desc,
    long_description_content_type="text/markdown",
    url="https://github.com/ozaydincan/ros2tui",
    packages=find_packages(),
    install_requires=[
        "textual>=0.40.0",
        "rich",
    ],
    entry_points={
        "console_scripts": [
            # Maps the terminal command 'h20tui' to the main() function
            # inside ros2tui/main.py
            "ros2tui = ros2tui.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Topic :: Software Development :: User Interfaces",
    ],
    python_requires=">=3.10",
    include_package_data=True,
)
