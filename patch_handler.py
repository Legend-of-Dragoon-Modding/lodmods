"""Provides functionality to create and apply patches.

This module contains functions to create and apply xdelta diff patches for
files in a file list. Used for creating and applying mods.

TODO: Update code to fit new version."""

import colorama
import copy
import glob
import mmap
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import traceback
from game_file_handler import extract_all_from_list, insert_all_from_list, swap_all_from_list, \
    process_block_range
from config_handler import read_config, numerical_sort, read_file_list, update_config, config_setup, \
    get_disc_dir, update_file_list
from disc_handler import backup_file, cdpatch, psxmode, _def_path

colorama.init()
BLOCKSIZE_PATTERN = re.compile(b'([\x00-\xff][\x00-\\x08]\x00\x00)')
MOVE_CURSOR = '\x1b[1A'
ERASE = '\x1b[2K'
missing = None


def update_mod_list(config_file, config_dict, version_list):
    config_dict['[Mod List]'] = {}
    for mod in glob.glob(os.path.join('mods', '**', 'patcher.config'), recursive=True):
        mod = os.path.dirname(mod)
        config_dict['[Mod List]'][mod] = 0

    if not config_dict['[Mod List]']:
        print('LODMods: No mods found. Make sure to unzip '
              'all mods and move them to the "mods" folder.')
        return

    available_mods = list(config_dict['[Mod List]'].keys())
    swap_required = []
    print('Available mods:')
    for i, mod in enumerate(available_mods, start=1):
        mod_config = read_config(os.path.join(mod, 'patcher.config'))
        if len(mod_config['[Game Discs]']) == 2:
            swap_required.append(True)
        elif len(mod_config['[Game Discs]']) == 1:
            swap_required.append(False)
        else:
            print('Invalid number of versions required for %s. Must be 1 or 2' %
                  mod)
        print(''.join(('  ', str(i), '. ', os.path.basename(mod))))
    print()

    while True:
        mod_list = input('Enter numbers of all desired mods from the above list, '
                         'separated by spaces (e.g. 1 5 6): ')
        mod_list = mod_list.strip()
        mod_list = re.sub('[ ][ ]+', ' ', mod_list)
        try:
            mod_list = [int(x) for x in mod_list.split(' ')]
        except ValueError:
            print('Invalid values')
        else:
            if any(x < 1 for x in mod_list) or \
                    any(x > len(available_mods) for x in mod_list):
                print('List contains one or more values outside the Mod List range\n')
                continue
            for num in mod_list:
                if swap_required[num - 1] and version_list[0] is None:
                    print('%s uses files from a secondary game version. '
                          'A source (swap) version must be specified when '
                          'installing a mod that requires it '
                          '(e.g. patch USA -s JPN)\n' %
                          os.path.basename(available_mods[num - 1]))
                    break
            else:
                break

    for num in mod_list:
        config_dict['[Mod List]'][available_mods[num - 1]] = 1

    update_config(config_file, config_dict)


def create_patches(list_file, game_files_dir, patch_dir, disc_dict):
    os.makedirs(patch_dir, exist_ok=True)
    xdelta_path = _def_path('xdelta3-3.0.11-x86_64.exe')

    files_list = read_file_list(list_file, disc_dict)['[PATCH]']
    print('\nPatcher: Creating patches')
    total_patches = 0
    for disc, disc_val in files_list.items():
        for key, val in disc_val.items():
            if not val[1]:
                continue
            for file in val[2:]:
                total_patches += 1

    patches_created = 0
    for disc, disc_val in files_list.items():
        for key, val in disc_val.items():
            if not val[1]:
                continue
            base_name = os.path.basename(key)
            for file in val[2:]:
                if 'OV_' in key.upper() or 'SCUS' in key.upper() \
                        or 'SCES' in key.upper() or 'SCPS' in key.upper():
                    base_dir = os.path.dirname(key)
                    os.makedirs(base_dir.replace(game_files_dir, patch_dir), exist_ok=True)
                    block_range = process_block_range(file[0], base_name)
                    file_name = '.'.join((base_name, block_range))
                    meta_dir = os.path.join(base_dir, 'meta')
                    meta_file = os.path.join(meta_dir, file_name)
                    new_file = os.path.join(base_dir, file_name)
                    old_file = ''.join((new_file, '.orig'))
                    patch_file = os.path.join(
                        base_dir.replace(game_files_dir, patch_dir),
                        '.'.join((os.path.basename(new_file), 'xdelta')))

                    return_val = subprocess.run([xdelta_path, '-e', '-f', '-n', '-s',
                                    old_file, new_file, patch_file])
                    if return_val.returncode == 0:
                        patches_created += 1

                    with open(meta_file, 'rb') as f:
                        while True:
                            word = f.read(4)
                            if word == b'\xff\xff\xff\xff':
                                break
                        comp_seq = f.read(os.path.getsize(meta_file) - f.tell())

                    with open(patch_file, 'rb+') as f:
                        f.seek(0, 2)
                        f.write(b'\xff\xff\xff\xff')
                        f.write(comp_seq)
                else:
                    base_dir = '_'.join((os.path.splitext(key)[0], 'dir'))
                    os.makedirs(base_dir.replace(game_files_dir, patch_dir), exist_ok=True)
                    file_name = ''.join((os.path.splitext(os.path.basename(key))[0], '_', file[0]))
                    new_file = os.path.join(base_dir, ''.join((file_name, '.BIN')))
                    old_file = ''.join((new_file, '.orig'))
                    patch_file = os.path.join(
                        base_dir.replace(game_files_dir, patch_dir),
                        '.'.join((os.path.basename(new_file), 'xdelta')))
                    return_val = subprocess.run([xdelta_path, '-e', '-f', '-s',
                                                 old_file, new_file, patch_file])
                    if return_val.returncode == 0:
                        patches_created += 1

                print('Patcher: %d/%d patches created' % (patches_created, total_patches), end='\r')

    print(ERASE + 'Patcher: Patch creation successful\n')


def patch(list_file, disc_dict_pair, patch_list):
    disc_dict = disc_dict_pair[1]
    swap_src_dict = disc_dict_pair[0]

    files_list = read_file_list(list_file, disc_dict, check_duplicates=True)

    print('LODModS: Creating/restoring disc backups')
    for disc, disc_val in disc_dict.items():
        try:
            if disc != 'All Discs':
                print('LODModS: Backing up %s' % disc, end='\r')
                backup_file(disc_val[0], True)
        except FileNotFoundError:
            print('LODModS: %s could not be found' % disc_val[0])
    print(ERASE + 'LODModS: Discs backed up')

    print('\nLODModS: Extracting files from discs')
    cdpatch(copy.deepcopy(disc_dict))
    cdpatch(copy.deepcopy(swap_src_dict))
    print('LODModS: Files extracted')

    print('\nLODModS: Extracting subfiles from files')
    extract_all_from_list(list_file, disc_dict)
    if swap_src_dict:
        extract_all_from_list(list_file, swap_src_dict, '[SWAP]')
    print('LODModS: Subfiles extracted')

    xdelta_path = _def_path('xdelta3-3.0.11-x86_64.exe')
    files_to_patch = files_list['[PATCH]']
    if files_to_patch:
        print('\nLODModS: Applying patches')

        total_files = len(patch_list)
        patches_applied = 0
        patch_dict = {}
        for disc, disc_val in files_to_patch.items():
            for key in sorted(disc_val.keys(), key=numerical_sort):
                if not disc_val[key][1]:
                    continue
                base_name = os.path.basename(key)
                for file in disc_val[key][2:]:
                    if 'OV_' in key.upper() or 'SCUS' in key.upper() \
                            or 'SCES' in key.upper() or 'SCPS' in key.upper():
                        base_dir = os.path.dirname(key)
                        block_range = process_block_range(file[0], base_name)
                        old_file = os.path.join(base_dir, '.'.join((base_name, block_range)))
                        patch_dict[old_file] = []
                        meta_dir = os.path.join(base_dir, 'meta')
                        meta_file = os.path.join(meta_dir, '.'.join((base_name, block_range)))
                        patch_dict[old_file].append(meta_file)
                    else:
                        base_dir = '_'.join((os.path.splitext(key)[0], 'dir'))
                        file_name = ''.join((os.path.splitext(
                            os.path.basename(key))[0], '_', file[0]))
                        old_file = os.path.join(base_dir, ''.join((file_name, '.BIN')))
                        patch_dict[old_file] = [None]
                    new_file = '.'.join((old_file, 'patched'))
                    patch_dict[old_file].append(new_file)
                    patch_dict[old_file].append(list())

                    to_match = '.'.join((os.path.basename(old_file), 'xdelta'))
                    i = 0
                    end = len(patch_list)
                    while i < end:
                        item = patch_list[i]
                        if to_match in item:
                            patch_dict[old_file][2].append(item)
                            del patch_list[i]
                            end -= 1
                        else:
                            i += 1

        for target_file, file_val in patch_dict.items():
            for patch_file in file_val[2]:
                if file_val[0] is not None:
                    backup_file(patch_file)
                    with open(patch_file, 'rb+') as f:
                        patch_data = f.read()
                    os.remove(patch_file)
                    comp_metadata = patch_data[patch_data.rfind(b'\xff\xff\xff\xff'):]
                    with open(patch_file, 'wb') as f:
                        f.write(patch_data[:patch_data.rfind(b'\xff\xff\xff\xff')])
                    with open(file_val[0], 'rb+') as f:
                        f.flush()
                        file_map = mmap.mmap(f.fileno(), 0)
                        f.seek(file_map.rfind(b'\xff\xff\xff\xff'))
                        f.write(comp_metadata)

                return_val = subprocess.run([xdelta_path, '-d', '-f', '-s',
                                             target_file, patch_file, file_val[1]],
                                            stdout=subprocess.DEVNULL)
                if return_val.returncode == 0:
                    patches_applied += 1
                shutil.copy(file_val[1], target_file)
                os.remove(file_val[1])

                if file_val[0] is not None:
                    shutil.copy('.'.join((patch_file, 'orig')), patch_file)
                    os.remove('.'.join((patch_file, 'orig')))

                print('LODModS: %d/%d files patched' %
                      (patches_applied, total_files), end='\r')

        print(ERASE + 'LODModS: Patches applied')

    if swap_src_dict:
        swap_all_from_list(list_file, disc_dict_pair)

    print('\nLODModS: Inserting subfiles into files')
    insert_all_from_list(list_file, disc_dict)
    print('LODModS: Subfiles inserted')

    print('\nLODModS: Inserting files into discs (may take several minutes)')
    cdpatch_dict = copy.deepcopy(disc_dict)
    for disc, disc_val in cdpatch_dict.items():
        for key in list(disc_val[1][1].keys()):
            if 'XA' not in key and 'IKI' not in key:
                del cdpatch_dict[disc][1][1][key]
            else:
                del disc_dict[disc][1][1][key]

    cdpatch(cdpatch_dict, '-i')
    psxmode(disc_dict)
    print(MOVE_CURSOR + ERASE + 'LODModS: Inserting files into discs\n'
                                'LODModS: Files inserted\n')

    print('LODModS: Discs successfully patched')


if __name__ == '__main__':
    multiprocessing.freeze_support()

    config_dict = read_config('lodmods.config')
    version = 'USA'
    swap = ('JPN', 'USA')
    config_setup('lodmods.config', config_dict, [swap[1], swap[0]], True)
    print('\n---------------------------------------------\n'
          'LODModS Patcher v 1.31 - (c) theflyingzamboni\n'
          '---------------------------------------------\n')
    print('----------------------------\n'
          'Additional Credits:\n'
          'CDPatch - (c) Neill Corlett\n'
          'PSX-Mode2 - (c) CUE\n'
          'Xdelta3 - (c) Josh MacDonald\n\n'
          'Links can be found in readme\n'
          '----------------------------\n')

    try:
        config_dict = read_config('lodmods.config')
        version = 'USA'
        swap = ('JPN', 'USA')
        list_file = config_dict['[File Lists]'][version]
        game_files_dir = config_dict['[Modding Directories]']['Game Files']
        patch_list = []

        if not config_dict['[Game Directories]']['USA'] or \
                not os.path.exists(config_dict['[Game Directories]']['USA']):
            us_dir, us_disc_list = get_disc_dir('USA')
            config_dict['[Game Directories]']['USA'] = us_dir
            for x in zip(list(config_dict['[Game Discs]']['USA'].keys())[1:], us_disc_list):
                config_dict['[Game Discs]']['USA'][x[0]][0] = x[1]

        if not config_dict['[Game Directories]']['JPN'] or \
                not os.path.exists(config_dict['[Game Directories]']['JPN']):
            print('If you are not using a mod that requires the Japanese version,'
                  ' just press ENTER')
            jp_dir, jp_disc_list = get_disc_dir('JPN', False)
            config_dict['[Game Directories]']['JPN'] = jp_dir
            for x in zip(list(config_dict['[Game Discs]']['JPN'].keys())[1:], jp_disc_list):
                config_dict['[Game Discs]']['JPN'][x[0]][0] = x[1]

        config_dict['[Mod List]'] = {}
        update_config('lodmods.config', config_dict)
        for mod in glob.glob(os.path.join('mods', '**', '*.config'), recursive=True):
            mod = os.path.dirname(mod)
            config_dict['[Mod List]'][mod] = 0

        if not config_dict['[Mod List]']:
            print('LODMods: No mods found. Make sure to unzip '
                  'all mods and move them to the "mods" folder.')
            sys.exit(0)

        available_mods = list(config_dict['[Mod List]'].keys())
        print('Available mods:')
        for i, mod in enumerate(available_mods, start=1):
            print(''.join(('  ', str(i), '. ', os.path.basename(mod))))
        print()

        while True:
            mod_list = input('Enter numbers of all desired mods from the above list, '
                             'separated by spaces (e.g. 1 5 6): ')
            mod_list = mod_list.strip()
            mod_list = re.sub('[ ][ ]+', ' ', mod_list)
            try:
                mod_list = [int(x) for x in mod_list.split(' ')]
            except ValueError:
                print('Invalid values')
            else:
                if any(x < 1 for x in mod_list) or \
                        any(x > len(available_mods) for x in mod_list):
                    print('List contains one or more values outside the Mod List range\n')
                    continue
                break

        for num in mod_list:
            config_dict['[Mod List]'][available_mods[num - 1]] = 1

        update_config('lodmods.config', config_dict)

        disc_dict_pair = []
        for version in swap:
            disc_dict = {}
            for disc in config_dict['[Game Discs]'][version].keys():
                if (disc != 'All Discs' and config_dict['[Game Discs]'][version][disc][0] != '') \
                        or (disc == 'All Discs' and
                            config_dict['[Game Discs]'][version]['Disc 4'][0] != ''):
                    img = config_dict['[Game Discs]'][version][disc][0] \
                        if disc != 'All Discs' \
                        else config_dict['[Game Discs]'][version]['Disc 4'][0]
                    disc_dir = os.path.join(version, disc)
                    disc_dict[disc] = [
                        os.path.join(config_dict['[Game Directories]'][version], img),
                        [os.path.join(game_files_dir, disc_dir),
                         config_dict['[Game Discs]'][version][disc][1]]]
            disc_dict_pair.append(disc_dict)

        update_file_list('file_list.txt', config_dict, disc_dict_pair[1])
        for mod, mod_val in config_dict['[Mod List]'].items():
            if not mod_val:
                continue
            for file in glob.glob(os.path.join(mod, 'patches', '**', '*.xdelta'), recursive=True):
                patch_list.append(file)

        print()
        swap_check = read_file_list(list_file, disc_dict_pair[1])
        if swap_check['[SWAP]'] and not \
                (all([val[0] for key, val in config_dict['[Game Discs]']['JPN'].items()])
                 or config_dict['[Game Directories]']['JPN']):
            print('Japanese game disc folder and file names must be specified when '
                  'using a mod that swaps files.')
            sys.exit(0)

        patch(list_file, disc_dict_pair, copy.deepcopy(patch_list))

        try:
            shutil.rmtree(game_files_dir)
        except PermissionError:
            print('LODModS: Could not delete %s' % game_files_dir)

    except FileNotFoundError:
        print(traceback.format_exc())
        print('LODModS: %s not found' % sys.exc_info()[1].filename)
    except SystemExit:
        pass
    except:
        print(traceback.format_exc())
    finally:
        block_range_pattern = re.compile('(\.{\d+-\d+})')
        for patch in patch_list:
            backup = '.'.join((patch, 'orig'))
            if block_range_pattern.search(patch) and os.path.exists(backup):
                backup_file(patch, True)
                os.remove(backup)

        input('\nPress ENTER to exit')

    """disc_dict = {}
    for disc, val in config_dict['[Game Discs]'][version].items():
        if config_dict['[Game Discs]'][version][disc][0] != '0':
            img = config_dict['[Game Discs]'][version][disc][0] \
                if disc != 'All Discs' \
                else config_dict['[Game Discs]'][version]['Disc 4'][0]
            disc_dir = os.path.join(version, disc)
            disc_dict[disc] = [
                os.path.join(config_dict['[Game Directories]'][version], img),
                [os.path.join(game_files_dir, disc_dir),
                 config_dict['[Game Discs]'][version][disc][1]]]
    create_patches(file_list, game_files_dir, patch_folder, disc_dict)"""
