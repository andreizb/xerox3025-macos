#!/usr/bin/env python3
"""Own a reviewed queue association for optional install and complete removal.

SPDX-License-Identifier: MIT
Python is an installer/uninstaller prerequisite only when association is used.
"""
import argparse
from pathlib import Path
import sys
import types


def load_association_module():
    path = Path(__file__).with_name('associate-queue.py')
    module = types.ModuleType('xerox_associate_queue')
    module.__file__ = str(path)
    # Run the hash-verified source directly, without creating or trusting an
    # additional persistent bytecode cache beside the maintenance tools.
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def stage(module, review, destination, hardware):
    review, manifest, _, _ = module.load_plan(review)
    module.require(manifest['status'] == 'reviewed' and not manifest.get('pending_operation'),
                   'Install requires an unapplied, unambiguous pre-reviewed association.')
    module.require(not manifest['toner_hook'], 'The accepted installer does not enable an experimental toner hook.')
    module.require(manifest['hardware_uuid'] == module.normal_uuid(hardware),
                   'Review belongs to a different printer than this bridge configuration.')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in ('manifest.json', 'original.ppd', 'apple-generated.ppd', 'candidate.ppd',
                 'changes.patch', 'ppd-validation.txt'):
        path = review / name
        if name in ('changes.patch', 'ppd-validation.txt') and not path.exists():
            continue
        module.private_write(destination / name, module.read_regular(path))
    module.load_plan(destination)
    print('Copied the validated review into private installation rollback storage. No queue change made.')


def apply(module, review):
    _, manifest, _, _ = module.load_plan(review)
    module.require(not manifest['toner_hook'], 'The accepted installer does not enable an experimental toner hook.')
    module.mutate(review)


def restore(module, review, staging=False):
    _, manifest, _, _ = module.load_plan(review)
    module.require(not manifest.get('pending_operation'),
                   'Association has an uncertain pending operation. Rollback files must be retained for review.')
    status = manifest['status']
    if status == 'reviewed':
        print('No recorded applied association to remove.')
    elif status == 'restored':
        print('This installation already restored its association.')
    else:
        module.require(not staging, 'Staging uninstall cannot remove an applied association; use normal maintenance.')
        module.require(status in ('applied', 'needs-review'), 'Unrecognized association state; rollback files retained.')
        module.mutate(review, restore=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--stage', type=Path, metavar='SOURCE_REVIEW')
    modes.add_argument('--apply', type=Path, metavar='OWNED_REVIEW')
    modes.add_argument('--restore', type=Path, metavar='OWNED_REVIEW')
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--printer-uuid')
    parser.add_argument('--staging', action='store_true')
    args = parser.parse_args(argv)
    module = load_association_module()
    try:
        if args.stage:
            module.require(args.destination and args.printer_uuid and not args.staging,
                           'Stage requires a destination and printer UUID.')
            stage(module, args.stage, args.destination, args.printer_uuid)
        else:
            module.require(not args.destination and not args.printer_uuid, 'Unexpected stage arguments.')
            if args.apply:
                module.require(not args.staging, 'Staging never applies a queue change.')
                apply(module, args.apply)
            else:
                restore(module, args.restore, staging=args.staging)
    except (module.ReviewError, OSError, ValueError, KeyError, module.subprocess.TimeoutExpired) as error:
        print('Association maintenance stopped: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
