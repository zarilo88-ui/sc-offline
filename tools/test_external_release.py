#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Focused 1D/2A/2B host withdrawal and published-artifact composition checks."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent

class ExternalRelease(unittest.TestCase):
    def test_crew_spawn_have_no_host_registration_link_or_tick(self):
        host = (ROOT / 'CMakeLists.txt').read_text()
        registry = (ROOT / 'src/builtins/builtins.h').read_text()
        ticks = (ROOT / 'src/dllmain.cpp').read_text()
        for feature in ('crew', 'spawn'):
            self.assertNotIn('k' + feature.title() + 'Builtin', registry)
            for suffix in ('plugin', 'ui'):
                self.assertNotIn(f'src/builtins/{feature}_{suffix}.cpp', host)
                self.assertFalse((ROOT / f'src/builtins/{feature}_{suffix}.cpp').exists())
        for marker in ('ProcessShipMenu(', 'ProcessCrew(', 'SpawnBuiltinOwnsTick', 'CrewBuiltinOwnsTick'):
            self.assertNotIn(marker, ticks)
        self.assertIn('src/npc.cpp', host)
        self.assertIn('src/spawner.cpp', host)  # unrelated build/fleet callers remain
        self.assertFalse((ROOT / 'src/builtins/loadout_ui.cpp').exists())
        shortcut = (ROOT / 'plugins/loadout/loadout.cpp').read_text()
        self.assertNotIn('Menu_RequestSpawnClass', shortcut)
        self.assertIn('"spawn.ship_options"', shortcut)
        self.assertFalse((ROOT / 'src/builtins/npc_ui.cpp').exists())

    def test_four_published_components_and_defaults(self):
        host = (ROOT / 'CMakeLists.txt').read_text()
        sdk = (ROOT / 'plugins/CMakeLists.txt').read_text()
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        for feature in ('creative', 'discord', 'crew', 'spawn'):
            self.assertNotIn(f'add_library(sc-offline-{feature}', host)
            self.assertIn(f'add_subdirectory({feature})', sdk)
            self.assertIn(f'check_{feature}_sdk.py', workflow)
            source = ROOT / f'plugins/{feature}'
            shipped = ROOT / f'data/plugins/{feature}'
            self.assertEqual((source / 'plugin.ini').read_text(), (shipped / 'plugin.ini').read_text())
            self.assertEqual((shipped / 'disabled').exists(), feature in ('creative', 'discord'))
        self.assertIn('external-sdk', workflow)
        self.assertIn('built-external', workflow)
        self.assertNotIn('build/data/plugins/creative/creative.dll', workflow)
        self.assertNotIn('built-creative', workflow)

    def test_multiplayer_is_proved_against_the_published_sdk_but_not_shipped(self):
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        matrix = re.search(r'feature: \[([^\]]*)\]', workflow)
        self.assertIsNotNone(matrix)
        self.assertIn('multiplayer', [name.strip() for name in matrix.group(1).split(',')])
        self.assertIn('needs: [build, inspector-sdk, npc-sdk, external-sdk]', workflow)
        # The release job copies the features it names; multiplayer is not one of them and has no shipped folder.
        self.assertIn('for feature in creative discord crew spawn mining; do', workflow)
        self.assertFalse((ROOT / 'data/plugins/multiplayer').exists())
        proof = (ROOT / 'tools/check_multiplayer_sdk.py').read_text()
        cmake = (ROOT / 'plugins/multiplayer/CMakeLists.txt').read_text()
        self.assertIn('add_test(NAME multiplayer-motion-buffer COMMAND multiplayer-motion-test --track-tests)', cmake)
        for test in ('multiplayer-module-workflow', 'multiplayer-motion-buffer'):
            self.assertIn(f"add_test(NAME {test}", cmake)
            self.assertIn(test, proof)

if __name__ == '__main__':
    unittest.main(verbosity=2)
