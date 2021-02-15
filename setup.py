from setuptools import setup


if __name__ == "__main__":
    setup(
        name="homelab-srv",
        setup_requires="setupmeta",
        versioning="branch(main):dev",
        author="Zoran Simic zoran@simicweb.com",
        url="https://github.com/zsimic/homelab-srv",
        python_requires=">=3.7",
        entry_points={
           "console_scripts": [
               "homelab-srv = homelab_srv:main",
            ],
        },
        classifiers=[
            "Development Status :: 2 - Pre-Alpha",
            # "Development Status :: 5 - Production/Stable",
            "Environment :: Console",
            "Intended Audience :: Developers",
            "Intended Audience :: End Users/Desktop",
            "Operating System :: MacOS",
            "Operating System :: POSIX",
            "Operating System :: POSIX :: Linux",
            "Operating System :: Unix",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: Implementation :: CPython",
            "Topic :: Software Development :: Libraries",
            "Topic :: System :: Installation/Setup",
            "Topic :: Utilities",
        ],
    )
