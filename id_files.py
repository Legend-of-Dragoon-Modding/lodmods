"""Takes list of scenes and sample of dialogue, uses it to find
all instances of each dialogue entered, writes filename and
of file dialogue is found in, plus scene number. If dialogue
found in multiple files, replaces scene number with ???? for
subsequent instances. If dialogue sample not found, writes
'File not found' in place of filename.

Copyright (C) 2019 theflyingzamboni
"""

from collections import OrderedDict
from copy import deepcopy
import fnmatch
import os
from pathlib import PurePath
from config_handler import numerical_sort, write_file_list
import re

END_DLG_FLAG = re.compile(b'[\x00-\xff][\x00-\x05]\xff\xa0[\x00-\x26]\x00')
FILETYPE_DICT = {'BPE': re.compile(b'^[\x00-\xff]{4}BPE\x1a'),
                 'DEFF': re.compile(b'^DEFF'),
                 'MCQ': re.compile(b'^MCQ'),
                 # 'MRG': re.compile(b'^MRG\x1a'), won't work because MRGs deleted in unpacking
                 'TIM': re.compile(b'^\x10\x00{3}'),
                 'TMD': re.compile(b'\x41\x00{3}'),
                 'TEXT': END_DLG_FLAG}


def build_index(dir_to_search, output_file):
    if not os.path.isdir(dir_to_search):
        print('%s not found' % dir_to_search)
        return

    # List out all files in directory being searched and loop through them.
    file_list = []
    for r, dn, fn in os.walk(dir_to_search):
        for f in fnmatch.filter(fn, '*.bin'):
            file_list.append(os.path.join(r, f))
    file_list.sort(key=numerical_sort)

    output_dict = OrderedDict()
    disc = None
    files_searched = 0
    total_files = len(file_list)
    update_percent = max(1, total_files // 250)
    print('Searching: 0%', end='\r')

    for index, file in enumerate(file_list):
        sect_index = None
        file_path = PurePath(file)
        file_parts = file_path.parts
        for i, x in enumerate(file_parts):
            if re.search('Disc [1234]|All Discs', x, re.IGNORECASE) \
                    and x not in output_dict:
                disc = x
                output_dict[disc] = OrderedDict()

            # Since the MRG files in the SECT folders are the only ones that
            # need to be searched to ID file types, ignore anything that
            # isn't in SECT.
            if re.match('sect$', x, re.IGNORECASE):
                sect_index = i
                break
        if sect_index is None:
            continue

        # Since the number of folders nested within SECT varies, work
        # backwards through folder levels until SECT is reached.
        for i, x in reversed(list(enumerate(file_parts))):
            if i == len(file_parts) - 1:
                patch_target = '1'
            elif i == sect_index + 1:
                break
            else:
                patch_target = '0'

            parent_file = file_parts[i - 1].upper().replace('_DIR', '.BIN')
            curr_file = x.upper().replace('_DIR', '.BIN')
            parent_file = ''.join(
                ('@', os.path.join(*file_parts[sect_index:i - 1], parent_file)))
            parent_file = parent_file.replace('\\', '/')
            file_num = str(os.path.splitext(curr_file)[0].split('_')[-1])
            file_num = file_num.replace('{', '').replace('}', '')

            # Set flag for whether file is a main file (DRGNx.BIN), and
            # whether file should be flagged for patching. Only bottom-
            # level files should be flagged. If a parent file is not in
            # the output_dict, add it with flags and set of file numbers,
            # otherwise add file number of child file to set.
            if parent_file not in output_dict[disc]:
                if ('drgn0.bin' in parent_file.lower()
                        or 'drgn1.bin' in parent_file.lower()
                        or 'drgn21.bin' in parent_file.lower()
                        or 'drgn22.bin' in parent_file.lower()
                        or 'drgn23.bin' in parent_file.lower()
                        or 'drgn24.bin' in parent_file.lower()):
                    is_main = '1'
                else:
                    is_main = '0'

                output_dict[disc][parent_file] = [is_main, {(file_num, patch_target)}]
            else:
                output_dict[disc][parent_file][1].add((file_num, patch_target))

        files_searched += 1
        if files_searched % update_percent == 0:
            print('Searching: %.1f%%' % round(
                files_searched / total_files * 100, 1), end='\r')

    print('Searching: 100%  \n')

    # Sort output_dict in numerical sorting order.
    for disc, disc_val in deepcopy(output_dict).items():
        for key in sorted(list(disc_val.keys()), key=numerical_sort):
            output_dict[disc].move_to_end(key)

    # Sort file numbers within each parent file.
    for disc, disc_val in output_dict.items():
        for key in disc_val.keys():
            output_dict[disc][key][1] = sorted(
                list(disc_val[key][1]), key=lambda tup: numerical_sort(tup[0]))

    # Generate output using output_dict.
    if output_file:
        output_dict = {'[PATCH]': output_dict, '[SWAP]': {}}
        write_file_list(output_file, output_dict)
    else:
        for disc, disc_val in output_dict.items():
            print(''.join(('#', disc)))
            for entry, entry_val in disc_val.items():
                print(''.join((entry, '\t', str(entry_val[0]))))
                for item in entry_val[1]:
                    print(item[0] + '\t' + item[1])
                else:
                    print()


def id_file_type(dir_to_search, file_type=None, header_pattern=None,
                 output_file=None):
    """
    Identifies files of given type by header or byte pattern.

    File types can be defined by either file type or byte pattern. Only
    one is required, and file type is given higher priority.
    If the desired file type is not already predefined, a raw byte pattern
    can be used instead. Please consider contacting dev to add file type
    if information is known. This function should mostly be used on files
    unpacked using the unpack_all() function in game_file_handler only, due
    to the removal of non-bottom-level files. Not doing so could result in
    inappropriately set is_patch_target flags on some files.

    dir_to_search : str
        Name of root directory to search
    file_type : str
        Type of file to search for; should be one of the listed known types
        (default: None)
    header_pattern : str
        Hex sequence to search for in header; known sequences should be added
        to type dict (default: None)
    output : str
        Name of file list text file to output results to
        (default: None [will print to console])
    """

    if not os.path.isdir(dir_to_search):
        print('%s not found' % dir_to_search)
        return

    try:
        file_type = file_type.upper()  # Raises AttributeError if None
        if file_type not in FILETYPE_DICT:
            raise KeyError
    except AttributeError:
        if header_pattern is None:
            print('Please provide either a file_type or header_pattern')
            return
        else:
            header_pattern = re.compile(b''.join((b'^', header_pattern)))
    except KeyError:
        print('File type not recognized. Currently recognized '
              'file types are %s' % list(FILETYPE_DICT.keys()))
        return

    # List out all files in directory being searched and loop through them.
    file_list = []
    for r, dn, fn in os.walk(dir_to_search):
        for f in fnmatch.filter(fn, '*.bin'):
            file_list.append(os.path.join(r, f))
    file_list.sort(key=numerical_sort)

    output_dict = OrderedDict()
    disc = None
    files_searched = 0
    total_files = len(file_list)
    update_percent = max(1, total_files // 250)
    print('Searching: 0%', end='\r')

    for index, file in enumerate(file_list):
        found_match = False
        sect_index = None

        # Read necessary data
        with open(file, 'rb') as f:
            # If file_type is TEXT, search for the end token pattern through
            # the full file. Otherwise, just read the first 16 bytes to match
            # the header.
            if file_type == 'TEXT':
                data = f.read()
            else:
                data = f.read(16)

        # Search for pattern matches
        if file_type == 'TEXT':
            match_list = END_DLG_FLAG.finditer(data)
            for m in match_list:
                if not m.start(0) % 2:
                    found_match = True
                    break
        elif (file_type is not None and FILETYPE_DICT[file_type].search(data)) \
                or (header_pattern is not None and header_pattern.search(data)):
            found_match = True

        # Add files with matches to output dictionary. If a match is found,
        # the file and all its parent files are added to the dict.
        if found_match:
            file_path = PurePath(file)
            file_parts = file_path.parts
            for i, x in enumerate(file_parts):
                if re.search('Disc [1234]|All Discs', x, re.IGNORECASE) \
                        and x not in output_dict:
                    disc = x
                    output_dict[disc] = OrderedDict()

                # Since the MRG files in the SECT folders are the only ones that
                # need to be searched to ID file types, ignore anything that
                # isn't in SECT.
                if re.match('sect$', x, re.IGNORECASE):
                    sect_index = i
                    break
            if sect_index is None:
                continue

            # Since the number of folders nested within SECT varies, work
            # backwards through folder levels until SECT is reached.
            for i, x in reversed(list(enumerate(file_parts))):
                if i == len(file_parts) - 1:
                    patch_target = '1'
                elif i == sect_index + 1:
                    break
                else:
                    patch_target = '0'

                parent_file = file_parts[i - 1].upper().replace('_DIR', '.BIN')
                curr_file = x.upper().replace('_DIR', '.BIN')
                parent_file = ''.join(
                    ('@', os.path.join(*file_parts[sect_index:i - 1], parent_file)))
                parent_file = parent_file.replace('\\', '/')
                file_num = str(os.path.splitext(curr_file)[0].split('_')[-1])
                file_num = file_num.replace('{', '').replace('}', '')

                # Set flag for whether file is a main file (DRGNx.BIN), and
                # whether file should be flagged for patching. Only bottom-
                # level files should be flagged. If a parent file is not in
                # the output_dict, add it with flags and set of file numbers,
                # otherwise add file number of child file to set.
                if parent_file not in output_dict[disc]:
                    if ('drgn0.bin' in parent_file.lower()
                            or 'drgn1.bin' in parent_file.lower()
                            or 'drgn21.bin' in parent_file.lower()
                            or 'drgn22.bin' in parent_file.lower()
                            or 'drgn23.bin' in parent_file.lower()
                            or 'drgn24.bin' in parent_file.lower()):
                        is_main = '1'
                    else:
                        is_main = '0'

                    output_dict[disc][parent_file] = [is_main, {(file_num, patch_target)}]
                else:
                    output_dict[disc][parent_file][1].add((file_num, patch_target))

        files_searched += 1
        if files_searched % update_percent == 0:
            print('Searching: %.1f%%' % round(
                files_searched / total_files * 100, 1), end='\r')

    print('Searching: 100%  \n')

    # Sort output_dict in numerical sorting order.
    for disc, disc_val in deepcopy(output_dict).items():
        for key in sorted(list(disc_val.keys()), key=numerical_sort):
            output_dict[disc].move_to_end(key)

    # Sort file numbers within each parent file.
    for disc, disc_val in output_dict.items():
        for key in disc_val.keys():
            output_dict[disc][key][1] = sorted(
                list(disc_val[key][1]), key=lambda tup: numerical_sort(tup[0]))

    # Generate output using output_dict.
    if output_file:
        output_dict = {'[PATCH]': output_dict, '[SWAP]': {}}
        write_file_list(output_file, output_dict)
    else:
        for disc, disc_val in output_dict.items():
            print(''.join(('#', disc)))
            for entry, entry_val in disc_val.items():
                print(''.join((entry, '\t', str(entry_val[0]))))
                for item in entry_val[1]:
                    print(item[0] + '\t' + item[1])
                else:
                    print()
