from setuptools import setup, find_packages

setup(
    name='ros2tui',
    version='0.1.0',
    description='A TUI for ROS 2',
    author='ozaydincan.app@gmail.com',
    packages=find_packages(),
    install_requires=[
        'textual>=0.40.0',
        'rich',
    ],
    entry_points={
        'console_scripts': [
            # This links the terminal command 'ros2tui' to your main() function
            'ros2tui = ros2tui.main:main',
        ],
    },
)
