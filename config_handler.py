"""
Provides functionality for handling LODModS config files and file lists.

This module contains functions with the config files that contain all of
the directory and disc information necessary for LODModS to function, as
well as the file list text files used to perform batch operations on the
games files (such as file extraction/insertion, decompression/compression,
and text dumping/insertion). These functions include config and file list
reading, setup, and updating, as well as duplication checking in the file
lists.

Copyright (C) 2019 theflyingzamboni
"""

from collections import OrderedDict
import copy
from functools import reduce
import glob
import os
import re
import sys

NUMBERS = re.compile(r'(\d+)')


class DuplicationError(Exception):
    pass


def numerical_sort(value):
    """
    Applies integer sorting to strings containing numbers.

    Splits string into compononent parts using integers as separators,
    then maps int onto the part list. The list is then returned and used
    as a sort key so that integers are int-sorted instead of str-sorted.

    Parameters
    ----------
    value : str
        Filename to be split and mapped to int.

    Returns
    -------
    str/int list
        List of component parts of filename.
    """

    parts = NUMBERS.split(value)
    parts[1::2] = map(int, parts[1::2])
    return parts


def _merge_dicts(dict1, dict2):
    """
    Recursive function to merge dicts of arbitrary depth.

    Used to merge the [PATCH] and [SWAP] sections of a file list txt file
    together (in dict form). Function is recursive to merge nested dicts
    with an arbitrary degree of nesting. This is necessary as the file list
    dicts are merged together differently depending on the purpose of the
    merge, and require different levels of nesting in the input dicts.

    Parameters
    ----------
    dict1 : dict
        First dict to be merged
    dict2 : dict
        Second dict to be merged

    Returns
    -------
    dict
        Merged dict
    """

    for key in dict2:
        if key in dict1:
            if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                # If the items stored at key in both dicts are also dicts, recurse
                # the function.
                _merge_dicts(dict1[key], dict2[key])
            elif isinstance(dict1[key], list) and isinstance(dict2[key], list):
                if isinstance(dict1[key][0], int) and isinstance(dict2[key][0], int):
                    # If the items stored at key are lists and the first item is,
                    # an int, add files from dict2 to dict1
                    dict1[key][0] = dict1[key][0] | dict2[key][0]
                    dict1[key][1] = dict1[key][1] | dict2[key][1]
                    dict1[key].extend(dict2[key][2:])
        else:  # If key is not in dict1, add it
            dict1[key] = dict2[key]
    return dict1


def _check_for_duplicates(file_list_dict):
    """
    Checks for duplicate entries in a file list txt file.

    Creates separate dicts for the [PATCH] and [SWAP] section of the
    file_list_dict. These dicts remove the extra layers of nesting
    ([PATCH]/[SWAP] and disc number) so that the dicts only contain one
    level with the parent files as keys. The two dicts are then merged
    together, and for each parent file, duplicate file numbers are checked
    for. If duplicates are detected, they are added to a formatted warning
    string and returned.

    Parameters
    ----------
    file_list_dict : dict
        Dict containing entries from file list txt file.

    Returns
    -------
    str
        Warning message for duplicate file list entries.
    """

    # Create separate dicts for the [PATCH] and [SWAP] sections
    # of the file list.
    try:
        patch_dict = {x: file_list_dict['[PATCH]'][disc][x]
                      for disc in file_list_dict['[PATCH]']
                      for x in file_list_dict['[PATCH]'][disc]}
    except KeyError:
        patch_dict = {}
    try:
        swap_dict = {x: file_list_dict['[SWAP]'][disc][x]
                     for disc in file_list_dict['[SWAP]']
                     for x in file_list_dict['[SWAP]'][disc]}
    except KeyError:
        swap_dict = {}

    merge_dict = reduce(_merge_dicts, [patch_dict, swap_dict])

    # First, compares length of list of file #s and set of file #s.
    # If the list has more than one item and at least one of them
    # is ^ or * (parent file or all files), add the file to the
    # duplicate dictionary at key (the file name). If the list and
    # set are not the same length, and none of the values are ^ or *,
    # enter the 'else' statement.
    dup_file_dict = {}
    for key, val in merge_dict.items():
        i = sorted([x[0] for x in val[2:]], key=numerical_sort, reverse=True)  # List of file #s
        k = set(i)  # Set of file #s
        if len(i) != len(k) or \
                (('*' in k or '^' in k or any('-' in s for s in k))
                 and len(k) > 1):
            if '^' in k:
                if key not in dup_file_dict:
                    dup_file_dict[key] = k
            elif '*' in k and val[1]:
                if key not in dup_file_dict:
                    dup_file_dict[key] = k
            else:
                if val[1]:  # If file is flagged as a mod target
                    dup_test_list = []

                    # Iterate through list of file #s, popping each item. If the item
                    # is a range, expand it. For each popped number, check if it exists
                    # in the dup_test_list. If it does, add it to the dup_file_dict for
                    # the appropriate parent file. At the end, append each popped item
                    # to dup_test_list.
                    for l in range(len(i[:])):
                        item = i.pop()
                        if '-' in item:
                            range_list = [str(x) for x in range(int(item.split('-')[0]),
                                                                int(item.split('-')[1]))]
                        else:
                            range_list = [item]
                        if any(num in dup_test_list for num in range_list):
                            if key not in dup_file_dict:
                                dup_file_dict[key] = list()
                            dup_file_dict[key].append(item)

                        dup_test_list.extend(range_list)

    # Add all of the entries in dup_file_dict to the error string with
    # the proper formatting.
    err_str = ''
    if dup_file_dict:
        for key, val in dup_file_dict.items():
            err_str = ''.join((err_str, '  ', os.path.basename(key),
                               '\n', '    File(s)/Block(s): ',
                               str(val)[1:-1].replace("'", ''), '\n'))

    return err_str


def read_config(config_file):
    """
    Reads a config file into an OrderedDict.

    Reads a .config text file into an OrderedDict with several layers
    of nesting. Dict structuring is as follows:

    [] = A category header. Top level of config_dict.
    # = A game version header (e.g. USA) for [Game Discs] category only.
        Second level of config_dict for that category.
    @ = Bottom-level dict. Used for information associated with specific
        game versions for [Game Directories], [File Lists], and [File Swap]
        categories. Used for toolset-level directories for [Modding Directories]
        and [Mod List]. Used for Disc # within version for [Game Discs].
    No formatting flag = Game file for a disc in [Game Discs].
    // = Comment. Not read into dict.
    = Separates a key from its value.

    Parameters
    ----------
    config_file : str
        Name of config text file to create config_dict from.

    Returns
    -------
    OrderedDict
        Dict containing structured information from config text file.
    """

    config_dict = OrderedDict()
    category = None
    version = None
    disc_num = None
    with open(config_file, 'r') as config:
        for line in config:
            line = line.strip('\n')
            if not line or line[:2] == '//':
                continue
            elif re.match(r'\[.*]', line):
                category = line
                config_dict[line] = {}
            elif line and line[0] == '#':
                version = line.strip('#').strip()
                config_dict[category][version] = {}
            elif line and line[0] == '@':
                key, val = [x.strip() for x in line.strip('@').split('=')]
                if category != '[Game Discs]':
                    config_dict[category][key] = \
                        val if category != '[Mod List]' else int(val)
                else:
                    disc_num = key
                    # noinspection PyTypeChecker
                    config_dict[category][version][disc_num] = [val, {}]
            elif line:
                key, val = [x.strip() for x in line.split('=')]
                # noinspection PyTypeChecker
                config_dict[category][version][disc_num][1][key] = int(val)

    return config_dict


def update_config(config_file, config_dict):
    """
    Updates a config text file.

    Updates the flags for game files in the [Game Discs] section based
    on the content of the individual config files of mods specified
    within config_file. That is, if a mod has the active flag for a
    particular file set in its own config file (e.g. OVL/S_ITEM.OV_=1),
    the flag in the main config file is updated to 1. All flags are
    initially zeroed out so that no extraneous files are extracted
    when applying patches.

    Parameters
    ----------
    config_file : str
        Name of config text file to update.
    config_dict : OrderedDict
        Dict with which to update config_file.
    """

    # Reset file values for all versions in [Game Discs] to 0 in config_dict
    for version, ver_val in config_dict['[Game Discs]'].items():
        for disc, disc_val in ver_val.items():
            for key in disc_val[1].keys():
                config_dict['[Game Discs]'][version][disc][1][key] = 0

    mods_config_list = [config_dict]  # Create a list of config_dicts for mods

    # For each mod flagged as 1 (true) in [Mod List], append its config dict
    # to the mods_config_list.
    for mod_path, mod_val in config_dict['[Mod List]'].items():
        if mod_val:
            config_name = glob.glob(os.path.join(mod_path, '*.config'))[0]
            mods_config_list.append({'[Game Discs]': read_config(config_name)['[Game Discs]']})

    # Shadows _merge_dicts function
    # Merges individual mod config dicts into main config dict in order
    # to set the appropriate game files in [Game Discs] to 1 for
    # extracting/inserting (e.g. OVL/S_ITEM.OV_=1). Headings/files are
    # added to the main dict if they are not already present.
    # noinspection PyShadowingNames
    def _merge_dicts(dict1, dict2):
        for k in dict2:
            if k in dict1:
                if isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
                    _merge_dicts(dict1[k], dict2[k])
                elif isinstance(dict1[k], list) and isinstance(dict2[k], list):
                    _merge_dicts(dict1[k][1], dict2[k][1])
                else:
                    dict1[k] = dict1[k] | dict2[k]
            else:
                dict1[k] = dict2[k]
        return dict1

    mods_config_dict = reduce(_merge_dicts, mods_config_list)

    # Format contents of config_dict and write to config_file.
    with open(config_file, 'w') as f:
        for cat, cat_val in mods_config_dict.items():
            f.write(''.join((cat, '\n')))
            if cat != '[Game Discs]':
                for key, val in cat_val.items():
                    if isinstance(val, int):
                        f.write(''.join(('@', key, '=', str(val), '\n')))
                    else:
                        f.write(''.join(('@', key, '=', val, '\n')))
                else:
                    f.write('\n')
            else:
                for version, ver_val in cat_val.items():
                    f.write(''.join(('#', version, '\n')))
                    for disc, disc_val in ver_val.items():
                        f.write(''.join(('@', disc, '=', disc_val[0], '\n')))
                        for file, file_val in disc_val[1].items():
                            f.write(''.join((file, '=', str(file_val), '\n')))
                        else:
                            f.write('\n')


def get_disc_dir(version, required=True):
    """
    Asks for the disc image directory and gets the disc images.

    Asks the user to input the name of the directory containing the disc
    images for the specified version, and attempts to identify the images
    within that directory. If the files for the discs are not correct, the
    user is asked to manually input the names of the files.

    Parameters
    ----------
    version : str
        Game version to get directory and images for (e.g. USA)
    required : boolean
        Whether the information for a particular version is required.

    Returns
    -------
    str, str list
        Returns the name of the directory oontaining the disc images
        and a list of the image file names.
    """

    while True:
        version_dir = input('Enter the full path of the folder '
                            'containing the %s game discs: ' % version)
        if not version_dir and required:
            # Repeat if dir required but not given.
            print('%s image directory is required\n' % version)
        elif not version_dir and not required:
            # Return empty strings if dir not given or required.
            print()
            return '', ['', '', '', '']
        if not os.path.exists(version_dir):
            # Repeat if dir given does not exist.
            print('"%s" not found\n' % version_dir)
        else:
            # Search dir for any file with the iso, bin, or img extension and
            # add them to disc_list, then remove anything that does not have
            # 'lod' or 'dragoon' in the name (educated guess since I've yet
            # to see an image on the English internet without one of those.).
            # Repeat dir request if at least 4 disc images aren't found.
            disc_list = []
            for ext in ('*.iso', '*.bin', '*.img'):
                disc_list.extend([os.path.basename(x) for x in
                                  glob.glob(os.path.join(version_dir, ext))])
            """disc_list = [disc for disc in disc_list if (
                    'lod' in disc.lower() or 'dragoon' in disc.lower())]"""
            if len(disc_list) < 4:
                print('Could not find four disc images in %s.\n'
                      'Make sure folder is correct and that all images '
                      'are present as ISO, BIN, or IMG files.\n'
                      'Patcher also expects either \'lod\' or \'dragoon\' '
                      'to be somewhere in the file name, in order to filter '
                      'out other games.' % version_dir)
            else:
                break

    # The Japanese versions seem to come with 2 tracks in seperate images.
    # The second track isn't of concern to the utilities, so remove them.
    # This may need to change eventually if people find a reason to mod
    # these files.
    if len(disc_list) > 4:
        for disc in disc_list[:]:
            if 'track 2' in disc.lower() or 'track2' in disc.lower():
                disc_list.remove(disc)

    disc_list.sort(key=numerical_sort)
    while True:
        # Print out the ID'd disc images.
        print('\nDisc images found:')
        for i, disc in enumerate(disc_list[:4], start=1):
            print(''.join(('  Disc ', str(i), ': ', disc)))
        print()

        # If the images listed are correct, break loop and return image
        # dir and list. If they are incorrect, prompt user to enter the
        # image names manually.
        response = input('Are these file names correct (y/n)? ')
        if response.lower() == 'y' or response.lower() == 'yes':
            break
        elif response.lower() == 'n' or response.lower() == 'no':
            print()
            disc_list = []
            i = 1
            while i <= 4:
                disc_name = input('Disc %d file name: ' % i)
                if not os.path.exists(os.path.join(version_dir, disc_name)):
                    print('"%s" not found\n' % os.path.join(version_dir, disc_name))
                    continue
                if 'iso' in disc_name.split('.')[-1].lower() or \
                        'bin' in disc_name.split('.')[-1].lower() or \
                        'img' in disc_name.split('.')[-1].lower():
                    disc_list.append(disc_name)
                    i += 1
                else:
                    print('Make sure file name has the ISO, BIN, or IMG extension\n')
        else:
            print('Enter "y" or "n"')

    print()
    return version_dir, disc_list


def config_setup(config_file, config_dict, version_list, called_by_patcher=False):
    """
    Set up a config file with directory and disc info.

    For each game version in version_list, check that the appropriate entries
    exist in the config text file via config_dict. If they do not, add them,
    and go through the process of getting the disc directory and image
    information from the user.

    Parameters
    ----------
    config_file : str
        Name of config text file to set up.
    config_dict : OrderedDict
        Dict of config_file to be set up.
    version_list : str list
        List of game versions to set up version info for.
    called_by_patcher : boolean
        Whether config_setup is called by the patcher or independently.
    """

    # Set up each version one at a time.
    for version in version_list:
        # Add version to [Game  Directories] in config_dict
        # if it's not already there.
        if version not in config_dict['[Game Directories]']:
            config_dict['[Game Directories]'][version] = ''

        # Add entries to [Game Discs] for version if they do not already
        # exist.
        if version not in config_dict['[Game Discs]']:
            config_dict['[Game Discs]'][version] = \
                dict([('All Discs', ['_'.join(('All', version)), {}]),
                     ('Disc 1', ['', {}]), ('Disc 2', ['', {}]),
                     ('Disc 3', ['', {}]), ('Disc 4', ['', {}])])

        # If the function was not called by the patcher, the version doesn't
        # exist in [Game Directories], or not all of the disc image names
        # for the version are filled in, then get the disc directory and
        # disc image names and add them to config_dict.
        if not called_by_patcher \
                or (config_dict['[Game Directories]'][version] == ''
                    or not all(val[0] for key, val in
                               list(config_dict['[Game Discs]'][version].items())[1:])):
            version_dir, version_disc_list = get_disc_dir(version)
            config_dict['[Game Directories]'][version] = version_dir
            for x in zip(list(config_dict['[Game Discs]'][version].keys())[1:],
                         version_disc_list):
                config_dict['[Game Discs]'][version][x[0]][0] = x[1]

    update_config(config_file, config_dict)


def read_file_list(list_file, disc_dict, reverse=False, merge_categories=False,
                   file_category='[ALL]', check_duplicates=False):
    """
    Read file list txt file to a dict.

    Reads a file list text file into a dict with several layers of nesting.
    Dict structuring is as follows:

    [] = A category header. Top level of config_dict.
    # = A disc number header (e.g. Disc 1).
    @ = A parent file header (e.g. OVL/S_ITEM.OV_).
    No formatting flag = Subfile within parent file.
    // = Comment. Not read into dict.

    Additionally, an individual parent file will have a value structured as
    a list: [sector padding/main file flag, mod target flag, [list of subfiles]].

    Several additional flags/parameters can be set depending on the context
    from which read_file_list() is used.

    list_file : str
        Name of file list text file to read.
    disc_dict : dict
        Dict of game disc info.
    reverse : boolean
        Flag to reverse sort order of subfiles (necessary when inserting
        files). (default: False)
    merge_categories : boolean
        Flag to merge separate [] list file categories into single [ALL]
        category. (default: False)
    file_category : str
        Category from list file to add to file_list_dict (default: [ALL]).
    check_duplicates : boolean
        Flag to check for duplicate file entries in list file.
        (default: False)

    Returns
    -------
    dict
        Returns file_list_dict built from list file.
    """

    category = None
    source_file = None
    disc_num = None
    file_list_dict = {}
    disc_list = list(disc_dict.keys())
    with open(list_file, 'r') as inf:
        for line in inf:
            line = line.strip('\n')
            if not line or line[:2] == '//':
                continue
            elif re.match(r'\[.*]', line):
                category = line
                file_list_dict[line] = {}
            elif line[0] == '#':
                disc_num = line.strip('#').strip()

                # Only include files from discs specified by user at runtime.
                if disc_num in disc_list or disc_num == 'All':
                    file_list_dict[category][disc_num] = {}
            elif line[0] == '@':
                params = [x.strip() for x in line.split('\t')]
                try:
                    source_file = os.path.join(disc_dict[disc_num][1][0],
                                               params[-3].replace('@', ''))
                    file_list_dict[category][disc_num][source_file][0] = int(params[-2])
                    file_list_dict[category][disc_num][source_file][1] = int(params[-1])
                except KeyError:
                    file_list_dict[category][disc_num][source_file] = [int(params[-2]),
                                                                       int(params[-1])]
            else:
                try:
                    file_list_dict[category][disc_num][source_file].append(
                        [x.strip() for x in line.split('\t')])
                except KeyError:
                    pass

    # If the file category is specified as [PATCH] or [SWAP], restrict
    # file_list_dict to that category.
    if file_category in ['[PATCH]', ['SWAP']]:
        file_list_dict = {file_category: file_list_dict[file_category]}

    # Check for duplicate files in the file_list_dict and print a warning
    # if any exist.
    if check_duplicates:
        err_str = _check_for_duplicates(copy.deepcopy(file_list_dict))
        try:
            if err_str:
                raise DuplicationError
        except DuplicationError:
            print("File Handler: The following files are duplicated"
                  " or overlap in the file list.\n"
                  "This may potentially cause any affected patches "
                  "not to work properly.\n"
                  "Check mod readmes for compatibility "
                  "information.\n('*' = all files/blocks, "
                  "'^' = current file')\n\n%s" % err_str)
            if '^' in err_str:
                print("File Handler: Cannot swap or patch both a file and"
                      "its subfiles.")
                sys.exit(4)

    # If specified, merge all file categories into a single [ALL] category.
    if merge_categories:
        file_list_dict = {'[ALL]': reduce(
            _merge_dicts, [val for key, val in file_list_dict.items()])}

    # Remove duplicate subfile numbers from files in file_list_dict.
    for cat, cat_val in file_list_dict.items():
        for disc, disc_val in cat_val.items():
            for key, val in disc_val.items():
                val_list = []
                for sl in val[2:]:
                    if sl[0] == '*':
                        val_list = [sl]
                        break
                    elif not any(sl[0] in x for x in val_list):
                        val_list.append(sl)
                val = val[:2]
                val.extend(sorted(val_list,
                                  key=lambda x: numerical_sort(x[0]),
                                  reverse=reverse))
                file_list_dict[cat][disc][key] = val

    return file_list_dict


def update_file_list(list_file, config_dict, disc_dict):
    """
    Updates main file list text file with file lists from specified mods.

    Merges the contents of the file list text files for all mods toggled
    on in the config file into a single file list.

    Parameters
    ---------
    list_file : str
        Name of file list text file to read.
    config_dict : OrderedDict
        Dict of config file.
    disc_dict : dict
        Dict of game disc info.
    """

    # Create a list of file_list_dict. Create empty main dict first,
    # then add the file_list_dicts for every mod specified in
    # config dict. Then, merge all dicts into the main dict.
    mods_file_list = [{'[PATCH]': {}, '[SWAP]': {}}]
    for mod_path, mod_val in config_dict['[Mod List]'].items():
        if mod_val:
            list_name = os.path.join(mod_path, 'file_list.txt')
            mods_file_list.append(read_file_list(list_name, disc_dict))
    mods_file_dict = reduce(_merge_dicts, mods_file_list)

    # Loop through all the files in the file dict, and if any of the subfile
    # lists contain a '*', make that the only entry in the subfile list
    # (avoids unnecessary subfile listings).
    for cat, cat_val in mods_file_dict.items():
        for disc, disc_val in cat_val.items():
            for key, val in disc_val.items():
                if not val[1] and any('*' in sl for sl in val[2:]):
                    for sl in val[2:]:
                        if sl[0] == '*':
                            val = val[:2]
                            val.append(sl)
                            mods_file_dict[cat][disc][key] = val
                            break

    # Remove the user's file path from the game file names, so the keys are
    # relative to the disc image (e.g. OVL/S_ITEM.OV_).
    for cat, cat_val in mods_file_dict.items():
        for disc, disc_val in cat_val.items():
            new_dict = {}
            for key, val in disc_val.items():
                new_key = str.replace(key, os.path.join(disc_dict[disc][1][0], ''), '')
                new_dict[new_key] = val
            else:
                mods_file_dict[cat][disc] = new_dict

    # Write the new file list dict to the specified list file with
    # proper formatting.
    with open(list_file, 'w') as f:
        for cat, cat_val in mods_file_dict.items():
            f.write(''.join((cat, '\n')))
            for disc, disc_val in cat_val.items():
                f.write(''.join(('#', disc, '\n')))
                for entry, entry_val in disc_val.items():
                    f.write(''.join(('@', entry, '\t', str(entry_val[0]),
                                     '\t', str(entry_val[1]), '\n')))
                    for item in entry_val[2:]:
                        f.write('\t'.join(item))
                        f.write('\n')
                    else:
                        f.write('\n')
