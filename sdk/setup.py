from setuptools import find_packages, setup


setup(
    name="signal-sdk",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["httpx>=0.27.0", "httpx-sse>=0.4.0"],
    python_requires=">=3.12",
)
