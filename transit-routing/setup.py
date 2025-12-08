"""
KindMap Transit Routing - C++ Extension Build Script

This script builds the pathfinding_cpp C++ extension module using pybind11.
"""

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
import sys
import os

class get_pybind_include(object):
    """Helper class to determine the pybind11 include path"""

    def __str__(self):
        import pybind11
        return pybind11.get_include()


ext_modules = [
    Extension(
        'pathfinding_cpp',
        sources=[
            'cpp_src/bindings.cpp',
            'cpp_src/engine.cpp',
            'cpp_src/data_loader.cpp',
            'cpp_src/utils.cpp',
        ],
        include_dirs=[
            'cpp_src',
            str(get_pybind_include()),
        ],
        language='c++',
        extra_compile_args=[
            '-std=c++17',
            '-O3',  # 최적화 레벨 3
            '-march=native',  # 현재 CPU에 맞춘 최적화
        ] if sys.platform != 'win32' else [
            '/std:c++17',
            '/O2',  # MSVC 최적화
            '/EHsc',  # 예외 처리
        ],
    ),
]


# Platform-specific build configuration
class BuildExt(build_ext):
    """Custom build extension"""

    def build_extensions(self):
        # Compiler-specific optimizations
        ct = self.compiler.compiler_type
        opts = []
        link_opts = []

        if ct == 'unix':
            opts.append('-DVERSION_INFO="%s"' % self.distribution.get_version())
            opts.append('-fvisibility=hidden')

        elif ct == 'msvc':
            opts.append('/DVERSION_INFO=\\"%s\\"' % self.distribution.get_version())

        for ext in self.extensions:
            ext.extra_compile_args = opts
            ext.extra_link_args = link_opts

        build_ext.build_extensions(self)


setup(
    name='pathfinding_cpp',
    version='1.0.0',
    author='KindMap Team',
    author_email='team@kindmap.com',
    description='High-performance Multi-Criteria RAPTOR pathfinding engine',
    long_description='''
    C++ implementation of the Multi-Criteria RAPTOR algorithm for
    accessible transit routing in Seoul Metro network. Optimized for
    wheelchair users, visually impaired, hearing impaired, and elderly passengers.
    ''',
    ext_modules=ext_modules,
    install_requires=[
        'pybind11>=2.6.0',
    ],
    cmdclass={'build_ext': BuildExt},
    zip_safe=False,
    python_requires='>=3.8',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Scientific/Engineering :: GIS',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: C++',
    ],
)
