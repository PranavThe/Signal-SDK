from setuptools import find_packages, setup

setup(
    name="signalops",
    version="0.2.0",
    description="Operational intelligence for AI agents. Human judgment should compound, not evaporate.",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Pranav Puranik",
    url="https://github.com/PranavThe/Signal-SDK",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.27.0",
        "httpx-sse>=0.4.0",
    ],
    python_requires=">=3.12",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
