#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Isolated multiplayer module build, tests and install check against the published SDK 2.2.0 archive.

Pass the release zip and its adjacent release SHA256SUMS. Everything happens in a new folder outside this
checkout, from a copy of plugins/multiplayer and its two test sources: the module is built only against the
extracted archive's public headers (no host header, no product header, no submodule). What it proves:

  1. the archive is the published one (SHA-256 against the release list and the pinned digest) and unpacks
     to exactly the files its own SHA256SUMS lists;
  2. the module builds as a native plugin with warnings as errors (MSVC /W4 /WX, or -Wall -Wextra -Werror);
  3. the deterministic tests pass: the workflow test (the real module loaded with synthetic public services)
     and the buffer part of the motion test (--track-tests: no module, no sockets, no real time). The motion
     test's module comparison runs about 25 s in real time and needs the unmodified #126 module, so CI leaves
     it to the local proof;
  4. the install holds the module and its plugin.ini and nothing else, and no `disabled` marker;
  5. the SDK's own sco-plugin-check loads the installed module and runs its no-argument commands;
  6. negative controls fail: a private host header, a product header, a private host symbol (POSIX only) in
     the module's source cannot build, and an archive with one changed byte or a list with another digest
     is refused.

Synthetic evidence only. Not run in game. This proof builds and stages the module but does not add it to
the release zip: the release job copies the five features it names, and multiplayer is not one of them.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
from check_inspector_sdk import contained, run, verify_extract

ROOT = Path(__file__).resolve().parent.parent

# The two tests CI runs. Their names are in plugins/multiplayer/CMakeLists.txt.
CI_TESTS = ('multiplayer-module-workflow', 'multiplayer-motion-buffer')
# The test sources the module's CMakeLists.txt reaches at ../../tools/.
TEST_SOURCES = ('multiplayer_workflow_test.cpp', 'multiplayer_motion_test.cpp')


def generator_arguments(generator):
    if os.name == 'nt':
        return ['-G', generator, '-A', 'x64']
    return ['-G', 'Unix Makefiles', '-DCMAKE_BUILD_TYPE=Release']


def copy_source(destination):
    """The module and the tests it builds, laid out as in the repository (the tests include ../plugins/...)."""
    shutil.copytree(ROOT / 'plugins/multiplayer', destination / 'plugins/multiplayer')
    (destination / 'tools').mkdir()
    for name in TEST_SOURCES:
        shutil.copy2(ROOT / 'tools' / name, destination / 'tools' / name)


def negative_archive_controls(archive, sums, work):
    """An archive with one changed byte, and a list that gives another digest, must both be refused."""
    folder = work / 'negative-archive'
    folder.mkdir()
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0x01
    mutated = folder / archive.name
    mutated.write_bytes(bytes(data))
    try:
        verify_extract(mutated, sums, folder / 'sdk-from-mutated-archive')
    except AssertionError as error:
        if 'SHA256 mismatch' not in str(error):
            raise
        print('multiplayer archive rejected: one changed byte')
    else:
        raise AssertionError('A changed archive was accepted')
    changed_sums = folder / 'SHA256SUMS'
    lines = []
    for line in sums.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip('*') == archive.name:
            line = '0' * 64 + '  ' + parts[1]
        lines.append(line)
    changed_sums.write_text('\n'.join(lines) + '\n')
    try:
        verify_extract(archive, changed_sums, folder / 'sdk-from-changed-list')
    except AssertionError as error:
        if 'SHA256 mismatch' not in str(error):
            raise
        print('multiplayer archive rejected: release list with another digest')
    else:
        raise AssertionError('A release list with another digest was accepted')


def negative_source_controls(sdk, work, generator):
    """Source the module must not be able to build: each mutation goes into a fresh copy of the source."""
    mutants = {
        'private host header': ('#include "sco/plugins.h"\n', 'sco/plugins.h', True),
        'product header': ('#include "version.h"\n', 'version.h', True),
        'private host symbol': ('extern void Menu_RequestClearNpcs();\n'
                                'namespace { struct Forbidden { Forbidden() { Menu_RequestClearNpcs(); } } forbidden; }\n',
                                'Menu_RequestClearNpcs', os.name != 'nt'),
    }
    for number, (label, (mutation, token, applies)) in enumerate(mutants.items(), 1):
        if not applies:
            print('multiplayer boundary control skipped on Windows: ' + label)
            continue
        source = work / f'mutant-{number}'
        copy_source(source)
        cpp = source / 'plugins/multiplayer/multiplayer.cpp'
        cpp.write_text(cpp.read_text() + '\n' + mutation)
        build = source / 'build'
        run(['cmake', '-S', source / 'plugins/multiplayer', '-B', build, *generator_arguments(generator),
             '-DSCO_SDK_INCLUDE_DIR=' + str(sdk / 'include')], work)
        result = run(['cmake', '--build', build, '--config', 'Release', '--target', 'sc-offline-multiplayer'], work, False)
        if not result.returncode or token not in result.stdout:
            raise AssertionError('Wrong negative-control result: ' + label + '\n' + result.stdout)
        print('multiplayer boundary rejected: ' + label)


def main(args):
    work = args.work.resolve()
    if contained(work, ROOT):
        raise AssertionError('Multiplayer proof must live outside the host checkout')
    work.mkdir(parents=True, exist_ok=False)
    archive, sums = args.archive.resolve(), args.sums.resolve()
    sdk, public = verify_extract(archive, sums, work / 'sdk')
    feature = ROOT / 'plugins/multiplayer'
    source = work / 'source'
    copy_source(source)
    generator = generator_arguments(args.generator)

    build = work / 'build'
    run(['cmake', '-S', source / 'plugins/multiplayer', '-B', build, *generator,
         '-DSCO_SDK_INCLUDE_DIR=' + str(sdk / 'include'), '-DSCO_WORKFLOW_TESTS=ON'], work)
    run(['cmake', '--build', build, '--config', 'Release', '--target',
         'sc-offline-multiplayer', 'multiplayer-module-test', 'multiplayer-motion-test'], work)
    tested = run(['ctest', '--test-dir', build, '-C', 'Release', '--no-tests=error', '-R',
                  '^(' + '|'.join(CI_TESTS) + ')$', '--output-on-failure', '-V'], work).stdout
    print(tested)
    if ('100% tests passed, 0 tests failed out of %d' % len(CI_TESTS)) not in tested:
        raise AssertionError('Expected exactly the two deterministic tests to pass')
    for token in ('multiplayer module: ', ' passed, 0 failed (synthetic public services; no sockets/game)',
                  'multiplayer motion (buffer only): '):
        if token not in tested:
            raise AssertionError('Missing test summary: ' + token)

    stage = work / 'stage'
    run(['cmake', '--install', build, '--config', 'Release', '--prefix', stage, '--component', 'multiplayer'], work)
    folder = stage / 'data/plugins/multiplayer'
    modules = [p for p in folder.iterdir() if p.suffix in ('.dll', '.so', '.dylib')]
    if len(modules) != 1 or (folder / 'disabled').exists():
        raise AssertionError('Multiplayer install inventory/default mismatch')
    if {p.name for p in folder.iterdir()} != {'plugin.ini', modules[0].name}:
        raise AssertionError('Unexpected files in installed multiplayer')
    if (folder / 'plugin.ini').read_bytes() != (feature / 'plugin.ini').read_bytes():
        raise AssertionError('Multiplayer install mismatch: plugin.ini')
    print('multiplayer install: native module and plugin.ini only, no disabled marker')

    # The SDK's own checker loads the installed module against its stand-in host. The installed folder stays
    # as installed; a copy gets the POSIX module name in its manifest.
    check_folder = work / 'checker-plugins/multiplayer'
    shutil.copytree(folder, check_folder)
    if os.name != 'nt':
        manifest = check_folder / 'plugin.ini'
        manifest.write_text(re.sub(r'(?m)^entry[ \t]*=.*$', 'entry = ' + modules[0].name, manifest.read_text()))
    checker_build = work / 'checker-build'
    run(['cmake', '-S', sdk, '-B', checker_build, *generator], work)
    run(['cmake', '--build', checker_build, '--config', 'Release', '--target', 'sco-plugin-check'], work)
    checker = checker_build / ('Release/sco-plugin-check.exe' if os.name == 'nt' else 'sco-plugin-check')
    checked = run([checker, check_folder, '--invoke', 'multiplayer.status'], work).stdout
    print(checked)
    for token in ('multiplayer.status -> ok', 'G13 unavailable (admission/provider)', 'OK: 0 failure(s)'):
        if token not in checked:
            raise AssertionError('Missing-service checker reply missing: ' + token)

    negative_archive_controls(archive, sums, work)
    negative_source_controls(sdk, work, args.generator)
    print('multiplayer SDK release proof: PASS (synthetic; not run in game)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sums', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True, help='New directory outside checkout')
    parser.add_argument('--generator', default='Visual Studio 18 2026',
                        help='CMake generator on Windows (x64); POSIX always uses Unix Makefiles')
    main(parser.parse_args())
