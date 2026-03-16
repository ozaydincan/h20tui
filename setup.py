from setuptools import find_packages, setup

setup(
    name="ros2tui",
    version="0.1.0",
    description="A TUI for ROS 2",
    author="Can Ozaydin",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ozaydincan/ros2tui",
    packages=find_packages(),
    install_requires=[
        "textual>=0.40.0",
        "rich",
    ],
    entry_points={
        "console_scripts": [
            # This links the terminal command 'ros2tui' to your main() function
            "ros2tui = ros2tui.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires=">=3.10",
)
