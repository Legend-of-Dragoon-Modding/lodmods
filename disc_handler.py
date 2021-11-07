"""
Provides functionality to handle disc images.

This module contains functions that deal with the disc images for LoD
(including iso, img, and bin files). The primary functions of this module
are wrappers that integrate Neill Corlett's cdpatch and CUE's psx-mode2
into the LODModS framework for extracting/inserting game files from/into
the disc images so that they can be further handled using the functions
in the game_file_handler module. Additionally, this module provides a
function to backup/restore backups of game discs and files.

Copyright (C) 2019 theflyingzamboni
"""

import os
import shutil
import subprocess
import sys


def _def_path(file_system_object):
    """
    Returns absolute file path of executable.

    Takes an executable file name and returns the absolute file path.
    Necessary for use in PyInstaller-created single-file executables,
    as the third-party executable dependencies for LODModS will be
    unpacked in a randomly-named temp folder.

    Parameters
    ----------
    file_system_object : str
        File name of executable

    Returns
    -------
    str
        Absolute file path of file_system_object (executable)
    """

    if getattr(sys, 'frozen', False):
        # noinspection PyUnresolvedReferences,PyProtectedMember
        return os.path.join(sys._MEIPASS, 'bin', file_system_object)
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            file_system_object)


def backup_file(input_file, restore_from_backup=False):
    """
    Creates/restores disc image backup.

    Creates a backup of the input disc image file with the .orig extension.
    If restore_from_backup is set to True, the image will be replaced by
    the clean .orig backup if it exists. Otherwise, a backup will be created
    normally. Backup files should not be deleted, as this could result in
    certain functions creating backups from modded files.

    Parameters
    ----------
    input_file : str
        Path/name of file to be backed up/restored from backup.
    restore_from_backup : boolean
        Flag determining whether file should be restored from clean backup
        (default: False).
    print_message : boolean
        Flag determining whether to print output (default: False).
    """

    # DO NOT DELETE .orig file if .bin file has been modified

    input_backup = ''.join((input_file, '.orig'))

    if not os.path.exists(input_backup):
        print(f'Backing up {input_file}')
        shutil.copy(input_file, input_backup)
    elif restore_from_backup:
        print(f'Restoring {input_file} from backup')
        shutil.copy(input_backup, input_file)


def cdpatch(disc_dict, mode='-x'):
    """
    Wrapper function for extracting/inserting game files with cdpatch.exe.

    Wraps Neill Corlett's cdpatch utility to integrate it with LODModS.
    For each disc listed in disc_dict, attempts to use cdpatch to extract
    or insert flagged game files, depending on how the mode flag is set.

    Cdpatch is the preferred game file extractor/inserter for XA audio
    only, as it is required for that. It is unable to handle inserting
    files of increased size, however, and this wrapper function will
    behave unexpectedly when trying to insert files from All Discs.

    Parameters
    ----------
    disc_dict : dict
        Dict of game disc info.
    mode : str
        Sets mode to extract (default; -x) or insert (-i).
    """

    # TODO: does not insert files for All Discs
    # Loop through each disc in disc_dict and add all flagged game files
    # to a list. Once all game files have been added, replace the game
    # file dict for that disc with the file list, as cdpatch requires
    # a list of files to extract/insert.
    for disc, disc_val in disc_dict.items():
        game_files_list = []
        for game_file, file_val in disc_val[1][1].items():
            if file_val == 1:
                game_files_list.append(game_file)
        disc_dict[disc][1][1] = game_files_list

    # Pop 'All Discs' key from disc_dict, then loop through the 'All Discs'
    # game file list. For each file, check whether it is present in the game
    # file lists for each individual disc. If it is not present, add it.
    # This is required to add 'All Discs' files to all discs. Only do this
    # for insertion, as 'All Discs' files should only be extracted once to
    # the appropriate folder.
    if mode == '-i':
        try:
            all_disc_files = disc_dict.pop('All Discs')
            for file in all_disc_files[1][1]:
                for disc, disc_val in disc_dict.items():
                    for item in disc_val[1][1]:
                        if os.path.basename(item) == os.path.basename(file):
                            break
                    else:
                        disc_dict[disc][1][1].append(file)
        except KeyError:
            pass  # Skip if 'All Discs' key not present.

    # For each disc in disc_dict, extract/insert all game files in
    # the file list.
    cdpatch_path = _def_path('cdpatch.exe')  # Get the absolute path of cdpatch
    for disc, disc_val in disc_dict.items():
        try:
            if disc_val[1][1] and mode == '-x':
                subprocess.run([cdpatch_path, mode, disc_val[0],
                                '-f', '-o', '-d', disc_val[1][0],
                                *disc_val[1][1]], stdout=subprocess.DEVNULL)
            elif disc_val[1][1] and mode == '-i':
                subprocess.run([cdpatch_path, mode, disc_val[0],
                                '-f', '-d', disc_val[1][0],
                                *disc_val[1][1]], stdout=subprocess.DEVNULL)
        except FileNotFoundError:
            print('CDPatch: %s could not be found' % sys.exc_info()[1].filename)


def psxmode(disc_dict, backup_discs=False):
    """
    Wrapper function for inserting game files with psx-mode2.exe.

    Wraps CUE's psx-mode2 utility to integrate it with LODModS.
    For each disc listed in disc_dict, attempts to use psx-mode2 to
    insert flagged game files.

    Psx-mode2 is used in instances where a file needs to be inserted
    that is larger than the original.

    Parameters
    ----------
    disc_dict : dict
        Dict of game disc info.
    backup_discs : boolean
        Flag to backup/restore from backup the discs being modified.
    """

    path_list = []

    # Loop through each disc in disc_dict and add all flagged game files
    # to a list. Once all game files have been added, replace the directory/
    # game file dict list with the full path game file list. Also add the
    # path for each disc to path_list.
    for disc, disc_val in disc_dict.items():
        path_list.append(disc_val[1][0])
        game_files_list = []
        for game_file, file_val in disc_val[1][1].items():
            if file_val == 1:
                game_files_list.append(os.path.join(disc_val[1][0], game_file))
        disc_dict[disc][1] = game_files_list

    # Pop 'All Discs' key from disc_dict, then loop through the 'All Discs'
    # game file list. For each file, check whether it is present in the game
    # file lists for each individual disc. If it is not present, add it.
    # This is required to add 'All Discs' files to all discs.
    try:
        all_disc_files = disc_dict.pop('All Discs')
        for file in all_disc_files[1]:
            for disc, disc_val in disc_dict.items():
                for item in disc_val[1]:
                    if os.path.basename(item) == os.path.basename(file):
                        break
                else:
                    disc_dict[disc][1].append(file)
    except KeyError:
        pass  # Skip if 'All Discs' key not present.

    # For each disc in disc_dict, insert all game files in the file list.
    psxmode_path = _def_path('psx-mode2-en.exe')
    for disc, disc_val in disc_dict.items():
        try:
            if not os.path.exists('.'.join((disc_val[0], 'orig'))):
                print('\nPSXMode: Creating %s backup\n' % disc)
                backup_file(disc_val[0], backup_discs, True)
            elif backup_discs:
                print('\nPSXMode: Restoring %s backup\n' % disc)
                backup_file(disc_val[0], backup_discs, True)

            files_to_insert = disc_val[1]
            for j, file in enumerate(files_to_insert):
                for path in path_list:
                    if path in file:
                        file = file.replace(path, '')
                        break

                # For XA and IKI files, the -n flag is necessary to skip
                # adding EDC/ECC data.
                if 'XA' in file.upper() or 'IKI' in file.upper():
                    subprocess.run([psxmode_path, disc_val[0], file,
                                    files_to_insert[j], '-n'],
                                   stdout=subprocess.DEVNULL)
                else:
                    subprocess.run([psxmode_path, disc_val[0], file,
                                    files_to_insert[j]],
                                   stdout=subprocess.DEVNULL)

        except FileNotFoundError:
            print('PSXMode: %s could not be found' % disc_val)
