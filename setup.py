from setuptools import setup, find_packages


setup(
    name="led-reading-plugin",
    version="0.1.6",
    description="Periodic LED readings for Pioreactor",
    author="Harley King",
    packages=find_packages(),
    include_package_data=True,
    install_requires=["pioreactor>=25.8.0"],
    entry_points={
        "pioreactor.plugins": [
            "led_reading_plugin = led_reading_plugin"
        ]
    },
)

from setuptools import setup, find_packages

