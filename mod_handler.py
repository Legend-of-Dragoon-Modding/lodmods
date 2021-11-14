"""Provides functionality to create and apply patches.

This module contains functions to create and apply xdelta diff patches for
files in a file list. Used for creating and applying mods."""

import colorama
from copy import deepcopy
import glob
import mmap
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import traceback
from config_handler import read_config, numerical_sort, read_file_list, update_config, config_setup, \
    update_file_list
from disc_handler import backup_file, cdpatch, psxmode, _def_path
from game_file_handler import extract_all_from_list, insert_all_from_list, swap_all_from_list, \
    process_block_range
from hidden_print import HiddenPrints

colorama.init()
BLOCKSIZE_PATTERN = re.compile(b'([\x00-\xff][\x00-\\x08]\x00\x00)')
MOVE_CURSOR = '\x1b[1A'
ERASE = '\x1b[2K'


def update_mod_list(config_file, config_dict, version_list):
    """
    Updates the mod list in the config file.

    Scans mods directory for available mods. The user is then asked which mods
    they wish to install. Mods to be installed are set equal to 1. At the end,
    the config file is updated with the new mod list.

    Parameters
    ----------
    config_file : str
        Name of config file to update.
    config_dict : OrderedDict
        Config dict object read from config file.
    version_list : str list
        List of game versions in config file (currently only USA and JPN).

    Returns
    -------
    bool
        Returns whether mods were found.
    """

    config_dict['[Mod List]'] = {}
    for mod in glob.glob(os.path.join('mods', '**', 'patcher.config'), recursive=True):
        mod = os.path.dirname(mod)
        config_dict['[Mod List]'][mod] = 0
    else:
        if not config_dict['[Mod List]']:
            print('LODMods: No mods found. Make sure to unzip '
                  'all mods and move them to the "mods" folder.')
            return False

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
            print(f'Invalid number of versions required for {mod}. Must be 1 or 2')
        print(f'  {str(i)}. {os.path.basename(mod)}')
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
                if swap_required[num - 1] and version_list[1] is None:
                    print('%s uses files from a secondary game version. '
                          'A source (swap) version must be specified when '
                          'installing a mod that requires it '
                          '(e.g. installmods USA -s JPN)\n' %
                          os.path.basename(available_mods[num - 1]))
                    break
            else:
                break

    for num in mod_list:
        config_dict['[Mod List]'][available_mods[num - 1]] = 1

    update_config(config_file, config_dict)

    return True


def create_patches(list_file, game_files_dir, patch_dir, disc_dict):
    """
    Creates xdelta patches for listed files.

    Goes through all files in the file list file and creates an xdelta diff
    patch if file is indicated as a mod target. Directory structure of the
    game files directory is maintained.

    If a patch is created for an OV_ file, additional compression metadata
    is appended to the end of the xdelta file for use in compression when
    patching. These files are only usable with LODModS, as they have extra
    data xdelta does not expect.

    Parameters
    ----------
    list_file : str
        Name of file list text file.
    game_files_dir : str
        Name of game files directory.
    patch_dir : str
        Name of patch files directory.
    disc_dict : dict
        Dict containing information about disc image, directory structure,
        and game files
    """

    os.makedirs(patch_dir, exist_ok=True)
    xdelta_path = _def_path('xdelta3-3.0.11-x86_64.exe')

    files_list = read_file_list(list_file, disc_dict, file_category='[PATCH]')['[PATCH]']
    print('\nPatcher: Creating patches')
    total_patches = 0
    for disc, disc_val in files_list.items():
        for key, val in disc_val.items():
            for file in val[1:]:
                if int(file[1]) == 1:
                    total_patches += 1

    patches_created = 0
    for disc, disc_val in files_list.items():
        for key, val in disc_val.items():
            base_name = os.path.basename(key)
            base_name_parts = base_name.split('.')
            for file in val[1:]:
                if int(file[1]) == 0:
                    continue
                if 'OV_' in key.upper() or 'SCUS' in key.upper() \
                        or 'SCES' in key.upper() or 'SCPS' in key.upper():
                    base_dir = os.path.join(''.join((os.path.splitext(key)[0], '_dir')))
                    os.makedirs(base_dir.replace(game_files_dir, patch_dir), exist_ok=True)
                    block_range = process_block_range(file[0], base_name)
                    file_name = f'{base_name_parts[0]}_{block_range}.{base_name_parts[1]}'
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
                    return_val = subprocess.run([xdelta_path, '-e', '-f', '-n', '-s',
                                                 old_file, new_file, patch_file])
                    if return_val.returncode == 0:
                        patches_created += 1

                print('Patcher: %d/%d patches created' % (patches_created, total_patches), end='\r')

    print(ERASE + 'Patcher: Patch creation successful\n')


def install_mods(list_file, disc_dict_pair, patch_list):
    """
    Applies mods to listed files.

    This function first extracts all game files and subfiles from the disc
    specified in the list file. Once extracted, each patch in patch list is
    applied to its respective file. Once all patches have been applied, file
    swap mods mods are applied if present. Finally, all of the files are
    repacked and inserted back into the disc.

    Parameters
    ----------
    list_file : str
        Name of file list text file.
    disc_dict_pair : dict tuple
        Pair of disc dicts (one each for dst and src).
    patch_list : str list
        List of file names of patches to apply.
    """

    dest_dict = disc_dict_pair[0]
    try:
        swap_src_dict = disc_dict_pair[1]
    except IndexError:
        swap_src_dict = {}

    files_list = read_file_list(list_file, dest_dict, check_duplicates=True)

    for disc, disc_val in dest_dict.items():
        try:
            if disc != 'All Discs':
                print(f'LODModS: Backing up {disc}', end='\r')
                with HiddenPrints():
                    backup_file(disc_val[0], True)
        except FileNotFoundError:
            print(f'LODModS: {disc_val[0]} could not be found')
            sys.exit(-8)
    print(ERASE + 'LODModS: Discs backed up')

    print('\nLODModS: Extracting files from discs')
    cdpatch(deepcopy(dest_dict), '-x', True)
    if swap_src_dict:
        cdpatch(deepcopy(swap_src_dict), '-x', True)
    print('LODModS: Files extracted')

    print('\nLODModS: Extracting subfiles from files')
    with HiddenPrints():
        extract_all_from_list(list_file, dest_dict)
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
                base_name = os.path.basename(key)
                base_name_parts = base_name.split('.')
                for file in disc_val[key][1:]:
                    if int(file[1]) == 0:
                        continue
                    if 'OV_' in key.upper() or 'SCUS' in key.upper() \
                            or 'SCES' in key.upper() or 'SCPS' in key.upper():
                        base_dir = os.path.join(f'{os.path.splitext(key)[0]}_dir')
                        block_range = process_block_range(file[0], base_name)
                        file_name = f'{base_name_parts[0]}_{block_range}.{base_name_parts[1]}'
                        file_to_patch = os.path.join(base_dir, file_name)
                        meta_dir = os.path.join(base_dir, 'meta')
                        meta_file = os.path.join(meta_dir, file_name)
                        patch_dict[file_to_patch] = []
                        patch_dict[file_to_patch].append(meta_file)
                    else:
                        base_dir = f'{os.path.splitext(key)[0]}_dir'
                        file_name = f'{base_name_parts[0]}_{file[0]}.{base_name_parts[1]}'
                        file_to_patch = os.path.join(base_dir, file_name)
                        patch_dict[file_to_patch] = []
                        patch_dict[file_to_patch].append(None)
                    new_file = f'{file_to_patch}.patched'
                    patch_dict[file_to_patch].append(new_file)
                    patch_dict[file_to_patch].append(list())

                    to_match = '.'.join((os.path.basename(file_to_patch), 'xdelta'))
                    i = 0
                    end = len(patch_list)
                    while i < end:
                        item = patch_list[i]
                        if to_match in item:
                            patch_dict[file_to_patch][2].append(item)
                            del patch_list[i]
                            end -= 1
                        else:
                            i += 1

        for target_file, file_val in patch_dict.items():
            for patch_file in file_val[2]:
                if file_val[0] is not None:
                    with HiddenPrints():
                        backup_file(patch_file)
                    with open(patch_file, 'rb+') as f:
                        patch_data = f.read()
                    os.remove(patch_file)
                    ff_offset = patch_data.rfind(b'\xff\xff\xff\xff')
                    comp_metadata = patch_data[ff_offset:]
                    with open(patch_file, 'wb') as f:
                        f.write(patch_data[:ff_offset])
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

                print(f'LODModS: {patches_applied:d}/{total_files:d} files patched',
                      end='\r')

        print(ERASE + 'LODModS: Patches applied')

    if swap_src_dict:
        swap_all_from_list(list_file, disc_dict_pair)

    print('\nLODModS: Inserting subfiles into files')
    with HiddenPrints():
        insert_all_from_list(list_file, dest_dict)
    print('LODModS: Subfiles inserted')

    print('\nLODModS: Inserting files into discs (may take several minutes)')
    cdpatch_dict = deepcopy(dest_dict)
    for disc, disc_val in cdpatch_dict.items():
        for key in list(disc_val[1][1].keys()):
            if 'XA' not in key and 'IKI' not in key:
                del cdpatch_dict[disc][1][1][key]
            else:
                del dest_dict[disc][1][1][key]

    if cdpatch_dict:
        cdpatch_dict_all = {k: v for k, v in cdpatch_dict.items() if k == 'All Discs'}
        if cdpatch_dict_all:
            for disc in ('Disc 1', 'Disc 2', 'Disc 3', 'Disc 4'):
                disc_path = cdpatch_dict_all['All Discs'][0]
                cdpatch_dict_all[disc] = [
                    disc_path, [cdpatch_dict_all['All Discs'][1][0], {}], '']
        cdpatch_dict_indiv = {k: v for k, v in cdpatch_dict.items() if k != 'All Discs'}

        cdpatch(cdpatch_dict_all, '-i', True)
        cdpatch(cdpatch_dict_indiv, '-i', True)
    psxmode(dest_dict, False, True)
    print(MOVE_CURSOR + ERASE + 'LODModS: Inserting files into discs\n'
                                'LODModS: Files inserted\n')

    print('LODModS: Discs successfully patched')


def main():
    multiprocessing.freeze_support()

    print('\n---------------------------------------------\n'
          'LODModS Patcher v 2.00 - (c) theflyingzamboni\n'
          '---------------------------------------------\n')
    print('----------------------------\n'
          'Additional Credits:\n'
          'CDPatch - (c) Neill Corlett\n'
          'PSX-Mode2 - (c) CUE\n'
          'Xdelta3 - (c) Josh MacDonald\n\n'
          'Links can be found in readme\n'
          '----------------------------\n')

    version = 'USA'  # Only version that can currently be modded
    swap = ('USA', 'JPN')
    patch_list = []

    try:
        config_dict = read_config('lodmods.config')
        swap = config_setup('lodmods.config', config_dict, swap, True)

        list_file = config_dict['[File Lists]'][version]
        game_files_dir = config_dict['[Modding Directories]']['Game Files']

        mods_found = update_mod_list('lodmods.config', config_dict, swap)
        if not mods_found:
            return

        disc_dict_pair = []
        for version in [s for s in swap if s is not None]:
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

        update_file_list(list_file, config_dict, disc_dict_pair[0])

        for mod, mod_val in config_dict['[Mod List]'].items():
            if not mod_val:
                continue
            for file in glob.glob(os.path.join(mod, 'patches', '**', '*.xdelta'), recursive=True):
                patch_list.append(file)

        print()
        swap_check = read_file_list(list_file, disc_dict_pair[0], file_category='[SWAP]')
        if swap_check['[SWAP]'] and not \
                (all([val[0] for key, val in config_dict['[Game Discs]']['JPN'].items()])
                 or config_dict['[Game Directories]']['JPN']):
            print('Japanese game disc folder and file names must be specified when '
                  'using a mod that swaps files.')
            sys.exit(0)

        install_mods(list_file, disc_dict_pair, deepcopy(patch_list))

        try:
            shutil.rmtree(game_files_dir)
        except PermissionError:
            print(f'LODModS: Could not delete {game_files_dir}')

    except FileNotFoundError:
        print(traceback.format_exc())
        print(f'LODModS: {sys.exc_info()[1].filename} not found')
    except SystemExit:
        pass
    finally:  # Need to restore compression metadata bytes to BPE patch files.
        with HiddenPrints():
            block_range_pattern = re.compile(r'(\.{\d+-\d+})')
            for p in patch_list:
                backup = '.'.join((p, 'orig'))
                if block_range_pattern.search(p) and os.path.exists(backup):
                    backup_file(p, True)
                    os.remove(backup)

        input('\nPress ENTER to exit')


if __name__ == '__main__':
    main()
