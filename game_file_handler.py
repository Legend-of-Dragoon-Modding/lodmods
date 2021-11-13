"""
Provides functionality to handle LoD's files once they're extracted from the discs.

This module contains 3 basic sets of functions: 1) BPE handling, 2) MRG handling,
and 3) file swap handling, as well as methods to execute these functions on
multiple files based off of file list text files defined in the config file.

BPE handling
------------
This set of functions deals with decompressing and compressing LoD's Byte-Pair
Encoded (BPE) files. This applies to all of the OV_ files, as well as a subsegment
of SCUS/SCES/SCPS and a number of subfiles in DRGN0.BIN.

MRG handling
------------
This set of functions deals with extracting subfiles from and inserting them into
LoD's MRG files, which are files that contain subfiles indexed using a logical-
block addressing (LBA) table. This applies to DRGN0.BIN, DRGN1.BIN, and DRGN2x.BIN,
as well as many of the subfiles in DRGN0.BIN and DRGN2x.BIN. Also contained are
methods to handle extracting from or inserting into multiple files using file
list text files. These functions also disinguishes BPEs and MRGs, and will handle
both [extract_from_list() and insert_from_list()].

File swapping
-------------
This set of functions deals with swapping game files between different versions
of LoD (e.g. Japanese to US), and likewise has a function to swap multiple files
using a file list text file.

Copyright (C) 2019 theflyingzamboni
"""

import colorama
import glob
from math import ceil
from more_itertools import sort_together
import multiprocessing
import os
import random
import re
import shutil
import sys
from config_handler import read_file_list, numerical_sort
from disc_handler import backup_file

MAIN_FILE = re.compile(r'(DRGN0\.bin)|(DRGN1\.bin)(DRGN2[1-4]\.bin)', re.I)
BPE_FLAG = re.compile(b'^[\x00-\xff]{4}BPE\x1a')
MRG_FLAG = re.compile(b'^MRG\x1a')
BLOCK_RANGE_PATTERN = re.compile(r'(_{\d+-\d+})')
BLOCK_RANGE_DICT = {'BTTL': ('{0-107}',), 'S_BTLD': ('{0-54}', '{0-32}'), 'S_EFFE': ('{0-62}',),
                    'S_INIT': ('{0-4}',), 'S_ITEM': ('{0-73}',), 'S_STRM': ('{0-41}',),
                    'SMAP': ('{0-104}',), 'TEMP': ('{0-11}',), 'TTLE': ('{0-17}',),
                    'WMAP': ('{0-96}',), 'SCUS_944': ('{0-448}',), 'SCUS_945': ('{0-448}',)}

colorama.init()
MOVE_CURSOR = '\x1b[1A'
ERASE = '\x1b[2K'


# BPE handling

def _choose_sort(attempt_num):
    """
    Choose the sort order for count_dict entries when creating
    a BPE compression dictionary. Introduces some variability into
    compressed block sizes helpful for getting compressed subfiles
    to equal their original compressed sizes.

    Parameters
    ----------
    attempt_num : int
        Number of times to attempt comressing a file

    Returns
    -------
    int
        Int that determines which sort order to use
    """

    x = 0
    if attempt_num <= 1:
        y = 0
    elif attempt_num == 2:
        x = y = 1
    elif attempt_num == 3:
        x = y = 2
    elif attempt_num == 4:
        x = y = 3
    elif attempt_num == 5:
        x = y = 4
    elif 5 < attempt_num <= 30:
        y = 1
    elif 30 < attempt_num <= 50:
        y = 2
    elif 50 < attempt_num <= 70:
        y = 3
    else:
        y = 4

    return random.randint(x, y)


def _sort_keys(count_dict, sort_order):
    """
    Sorts byte-pair dict keys according to sort_order int.

    Sorts byte-pair dictionary keys into a list, using sort_order to determine
    how they are sorted. Byte pairs are always sorted primarily by count;
    however, the game does not seem to have a consistent order for subsorting
    byte pairs with the same count. Depending on how byte pairs are subsorted
    according to each byte's value (e.g. 1st byte ascending, 2nd byte
    descending), the block may compress to a different size. Since it is
    necessary for modding to compress a file to <= its original size, varying
    sort order can help achieve smaller compressed size.

    Parameters
    ----------
    count_dict : dict
        Dict containing byte-pairs and the number of times they occur.
    sort_order : int
        Int indicating how byte pairs should be sorted.

    Returns
    -------
    list
        Sorted list of tuples containing the byte-pair and its count.
    """

    if sort_order == 0:
        bp_count_list = sorted(
            [(key, count_dict[key]) for key in count_dict.keys()],
            key=lambda tup: -tup[1])
    elif sort_order == 1:
        bp_count_list = sorted(
            [(key, count_dict[key]) for key in count_dict.keys()],
            key=lambda tup: (-tup[1], tup[0][0], tup[0][1]))
    elif sort_order == 2:
        bp_count_list = sorted(
            [(key, count_dict[key]) for key in count_dict.keys()],
            key=lambda tup: (-tup[1], -tup[0][0], tup[0][1]))
    elif sort_order == 3:
        bp_count_list = sorted(
            [(key, count_dict[key]) for key in count_dict.keys()],
            key=lambda tup: (-tup[1], tup[0][0], -tup[0][1]))
    else:
        bp_count_list = sorted(
            [(key, count_dict[key]) for key in count_dict.keys()],
            key=lambda tup: (-tup[1], -tup[0][0], -tup[0][1]))

    return bp_count_list


def process_block_range(range_entry, base_name):
    """
    Formats a compression-block range as a file extension.

    Takes an '*', number, or hyphenated number range and formats it as
    a {#-#} file extension, as used for BPE decompressed files.

    Parameters
    ----------
    range_entry : str
        A number, number range, or '*'.
    base_name : str
        File name to which block range extension is appended.

    Returns
    -------
    str
        {#-#} BPE-decompressed file block range extension.
    """
    if '-' in range_entry:
        block_range = ''.join(('{', range_entry, '}'))
    elif range_entry == '*':
        if 'S_BTLD' in base_name and len(BLOCK_RANGE_PATTERN.findall(base_name)) == 0:
            block_range = BLOCK_RANGE_DICT['S_BTLD'][0]
        elif 'S_BTLD' in base_name and len(BLOCK_RANGE_PATTERN.findall(base_name)) == 1:
            block_range = BLOCK_RANGE_DICT['S_BTLD'][1]
        else:
            block_range = BLOCK_RANGE_DICT[base_name.split('.')[0]][0]
    elif '-' not in range_entry:
        if 'S_BTLD' in base_name and len(BLOCK_RANGE_PATTERN.findall(base_name)) == 0:
            block_range = BLOCK_RANGE_DICT['S_BTLD'][0].replace('{0', ''.join(('{', range_entry)))
        elif 'S_BTLD' in base_name and len(BLOCK_RANGE_PATTERN.findall(base_name)) == 1:
            block_range = BLOCK_RANGE_DICT['S_BTLD'][1].replace('{0', ''.join(('{', range_entry)))
        else:
            block_range = BLOCK_RANGE_DICT[base_name.split('.')[0]][0].replace(
                '{0', ''.join(('{', range_entry)))
    else:  # No other values are acceptable for number ranges.
        raise ValueError

    return block_range


def _decompress(compressed_file, start_block=0, end_block=512, is_subfile=False):
    """
    Decompresses LoD's BPE-compressed files.

    LoD compresses some files using a form of blocked byte-pair encoding
    algorithm. The original data is compressed in blocks of up to 0x800
    decompressed bytes. Each compressed block is composed of a 4-byte header
    specifying the size of the decompressed block, instructions for filling
    out a byte-pair dictionary, and the compressed data.

    Decompression works by reading bytes as instructions for building the
    byte-pair dictionary, filling it out until the offset exceeds the
    dictionary size (256 bytes). Once the dictionary is filled out, bytes
    are read as compressed data, and either added to the list of decompressed
    data (if it is a real value) or used to get the corresponding byte-pair
    value until their are no more bytes left in the compressed block.

    Parameters
    ----------
    compressed_file : BufferedReader
        I/O file object of compressed file.
    start_block : int
        Data block to start decompression from. (default: 0)
    end_block : int
        Data block to decompress up to (non-inclusive). (default: 512)
    is_subfile : bool
        Flag indicating whether file is a BPE file, or a non-BPE file
        that contains BPE-compressed data within its body. (default: False)
    """

    # Make sure file is BPE, or has BPE subfile if is_subfile specified,
    # then set pointer to start of BPE file/subfile.
    if b'BPE\x1a' in compressed_file.read(8):
        compressed_file.seek(0)
    elif is_subfile:
        while True:
            word = compressed_file.read(4)
            if word == b'BPE\x1a':
                compressed_file.seek(compressed_file.tell()-8)
                break
    else:
        print('Decompress: Not a BPE file')
        print('Decompress: Skipping file')
        return

    file_name = os.path.realpath(compressed_file.name)
    basename = os.path.splitext(os.path.basename(file_name))
    bpe_subdir = '_'.join((os.path.splitext(file_name)[0], 'dir'))
    meta_dir = os.path.join(bpe_subdir, 'meta')
    os.makedirs(bpe_subdir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)

    decompressed_file_name = os.path.join(
        bpe_subdir,
        ''.join((basename[0], '_{', str(start_block),
                 '-', str(end_block), '}', basename[1])))
    meta_file = os.path.join(meta_dir, os.path.basename(decompressed_file_name))

    compressed_file.read(8)  # file size and BPE

    block = -1
    if end_block <= start_block:
        print('Decompress: End block is not greater than start block. '
              'Decompressing through end of file.')
        end_block = 512

    decompressed_file_offset = 0
    blocksize_list = []
    decompressed_byte_list = []

    while True:
        block += 1

        # Each block is preceded by 4-byte int up to 0x800 giving the number
        # of decompressed bytes in the block. 0x00000000 indicates that there
        # are no further blocks and decompression is complete.
        bytes_remaining_in_block = compressed_file.read(4)
        if bytes_remaining_in_block == b'\x00\x00\x00\x00'\
                or bytes_remaining_in_block == b'':
            break
        elif int.from_bytes(bytes_remaining_in_block, 'little') > 0x800:
            print('Decompress: 0x%s at offset 0x%08x is an invalid block size' %
                  (bytes_remaining_in_block.hex(), compressed_file.tell()-4))
            print('Decompress: Skipping file')
            return

        # If the routine has not reached the specified starting block, just
        # increment the decompressed file offset. If it's between start and
        # end, add the block size to the list of block sizes. Break the loop
        # once the end block is passed.
        if start_block > block:
            decompressed_file_offset += int.from_bytes(bytes_remaining_in_block, 'little')
        elif start_block <= block < end_block:
            blocksize_list.append(bytes_remaining_in_block)
        else:
            break

        bytes_remaining_in_block = int.from_bytes(bytes_remaining_in_block, 'little')

        # Build the initial dictionary/lookup table. The left-character dict
        # is filled so that each key contains itself as a value, while the
        # right-character dict is filled with empty values.
        dict_leftch = {x: x for x in range(0x100)}
        dict_rightch = {x: '' for x in range(0x100)}

        # Build adaptive dictionary.
        key = 0x00
        while key < 0x100:  # Dictionary is 256 bytes long. Loop until all keys filled.
            # If byte_pairs_to_read is >=0x80, then only the next byte will
            # be read into the dictionary, placed at the index value calculated
            # using the below formula. Otherwise, the byte indicates how many
            # sequential bytes to read into the dictionary.
            byte_pairs_to_read = int.from_bytes(compressed_file.read(1), 'big')
            if byte_pairs_to_read >= 0x80:
                key = key - 0x7f + byte_pairs_to_read
                byte_pairs_to_read = 0
            else:
                byte_pairs_to_read = byte_pairs_to_read

            # For each byte/byte pair to read, read the next byte and add it
            # to the leftch dict at the current key. If the character matches
            # the key it's at, increment key and continue. If it does not,
            # read the next character and add it to the same key in the
            # rightch dict before incrementing key and continuing.
            if key < 0x100:  # Check that dictionary length not exceeded.
                for i in range(byte_pairs_to_read+1):
                    compressed_byte = int.from_bytes(compressed_file.read(1), 'big')
                    dict_leftch[key] = compressed_byte

                    if compressed_byte != key:
                        compressed_byte = int.from_bytes(compressed_file.read(1), 'big')
                        dict_rightch[key] = compressed_byte

                    key += 1

        # Decompress block
        # On each pass, read one byte and add it to a list of unresolved bytes.
        while bytes_remaining_in_block > 0:
            compressed_byte = int.from_bytes(compressed_file.read(1), 'big')
            unresolved_byte_list = [compressed_byte]

            # Pop the first item in the list of unresolved bytes. If the
            # byte key == value in dict_leftch, append it to the list of
            # decompressed bytes. If the byte key != value in dict_leftch,
            # insert the leftch followed by rightch to the unresolved byte
            # list. Loop until the unresolved byte list is empty.
            while unresolved_byte_list:
                compressed_byte = unresolved_byte_list.pop(0)
                if compressed_byte == dict_leftch[compressed_byte]:
                    if block >= start_block:
                        decompressed_byte_list.append(compressed_byte.to_bytes(1, 'big'))
                    bytes_remaining_in_block -= 1
                else:
                    unresolved_byte_list.insert(0, dict_rightch[compressed_byte])
                    unresolved_byte_list.insert(0, dict_leftch[compressed_byte])

        if compressed_file.tell() % 4 != 0:  # Word-align the pointer.
            compressed_file.seek(compressed_file.tell()+(4-compressed_file.tell() % 4))

    # Create a file containing metadata necessary for re-compressing the file.
    # This includes the decompressed length of the block, the blocks that
    # decompression was started and end on, and the sizes of each block.
    with open(meta_file, 'wb') as outf:
        outf.write(len(decompressed_byte_list).to_bytes(4, 'little'))
        outf.write(start_block.to_bytes(2, 'little'))
        if end_block > block:
            outf.write(block.to_bytes(2, 'little'))
        else:
            outf.write(end_block.to_bytes(2, 'little'))
        for blocksize in blocksize_list[:end_block + 1]:
            outf.write(blocksize)
        outf.write(b'\xff' * 4)

    # Write decompressed file.
    with open(decompressed_file_name, 'wb') as outf:
        for byte in decompressed_byte_list:
            outf.write(byte)

    # Updates filenames if end_block exceeded the actual number of blocks.
    if end_block > block:
        updated_name = decompressed_file_name.replace(str(end_block)+'}', str(block)+'}')
        updated_meta = os.path.join(meta_dir, os.path.basename(updated_name))
        if os.path.exists(updated_name):
            os.remove(updated_name)
        if os.path.exists(updated_meta):
            os.remove(updated_meta)
        os.rename(decompressed_file_name, updated_name)
        os.rename(meta_file, updated_meta)
    print('Decompress: File decompressed\n')


def run_decompression(compressed_file, start_block=0, end_block=512, is_subfile=False):
    """
    Wrapper function for _decompress().

    Exits function if compressed file does not exist; otherwise, calls
    _decompress on the specified compressed file.

    Note: Although individual or ranges of blocks can be decompressed/
    compressed, it is advised to simply decompress/compress the entire
    file at once, as this will permit compatibility with other mods.

    Parameters
    ----------
    compressed_file : str
        Name of the file to be decompressed.
    start_block : int
        Data block to start decompression from. (default: 0)
    end_block : int
        Data block to decompress up to (non-inclusive). (default: 512)
    is_subfile : bool
        Flag indicating whether file is a BPE file, or a non-BPE file
        that contains BPE-compressed data within its body. (default: False)
    """

    print('Decompress: Decompressing file %s' % compressed_file)
    if not os.path.isfile(compressed_file):
        print('Decompress: %s does not exist' % compressed_file)
        print('Decompress: Skipping file')
        return

    with open(compressed_file, 'rb') as inf:
        _decompress(inf, start_block, end_block, is_subfile)


def _dummy_decompress(compressed_file, start_block=0, end_block=512, is_subfile=False):
    """
    "Fake" decompresses BPE file to find offsets of start and end blocks.

    For notes on decompression, see docstring and comments on _decompress. The
    sole purpose of this function is to decompress a BPE file without writing
    the decompressed data to a new file to get the start and end block offsets
    needed for _compression().

    Parameters
    ----------
    compressed_file : BufferedReader
        I/O file object of compressed file.
    start_block : int
        Data block to start decompression from. (default: 0)
    end_block : int
        Data block to decompress up to (non-inclusive). (default: 512)
    is_subfile : bool
        Flag indicating whether file is a BPE file, or a non-BPE file
        that contains BPE-compressed data within its body. (default: False)

    Returns
    -------
    (int, int, int)
        Offsets of start and end block and subfile start within compressed
        file, respectively.
    """

    subfile_start = None
    if is_subfile:
        while True:
            word = compressed_file.read(4)
            if word == b'BPE\x1a':
                subfile_start = compressed_file.tell() - 8
                compressed_file.seek(compressed_file.tell())
                break
    else:
        compressed_file.seek(8)

    block = -1
    start_block_offset = 8
    if end_block <= start_block:
        print('Decompress: End block is not greater than start block. '
              'Decompressing through end of file.')
        end_block = 512

    decompressed_file_offset = 0
    blocksize_list = []
    decompressed_byte_list = []

    while True:
        block += 1
        if block == start_block:
            start_block_offset = compressed_file.tell()

        bytes_remaining_in_block = compressed_file.read(4)
        if bytes_remaining_in_block == b'\x00\x00\x00\x00' \
                or bytes_remaining_in_block == b'':
            break
        elif int.from_bytes(bytes_remaining_in_block, 'little') > 0x800:
            print('Decompress: 0x%s at offset 0x%08x is an invalid block size' %
                  (bytes_remaining_in_block.hex(), compressed_file.tell() - 4))
            raise ValueError

        if start_block > block:
            decompressed_file_offset += int.from_bytes(bytes_remaining_in_block, 'little')
        elif start_block <= block < end_block:
            blocksize_list.append(bytes_remaining_in_block)
        else:
            break

        bytes_remaining_in_block = int.from_bytes(bytes_remaining_in_block, 'little')

        dict_leftch = {x: x for x in range(0x100)}
        dict_rightch = {x: '' for x in range(0x100)}

        key = 0x00
        while key < 0x100:
            byte_pairs_to_read = int.from_bytes(compressed_file.read(1), 'big')
            if byte_pairs_to_read >= 0x80:
                key = key - 0x7f + byte_pairs_to_read
                byte_pairs_to_read = 0
            else:
                byte_pairs_to_read = byte_pairs_to_read

            if key < 0x100:
                for i in range(byte_pairs_to_read + 1):
                    compressed_byte = int.from_bytes(compressed_file.read(1), 'big')
                    dict_leftch[key] = compressed_byte

                    if compressed_byte != key:
                        compressed_byte = int.from_bytes(compressed_file.read(1), 'big')
                        dict_rightch[key] = compressed_byte

                    key += 1

        while bytes_remaining_in_block > 0:
            compressed_byte = int.from_bytes(compressed_file.read(1), 'big')
            unresolved_byte_list = [compressed_byte]

            while unresolved_byte_list:
                compressed_byte = unresolved_byte_list.pop(0)
                if compressed_byte == dict_leftch[compressed_byte]:
                    if block >= start_block:
                        decompressed_byte_list.append(compressed_byte.to_bytes(1, 'big'))
                    bytes_remaining_in_block -= 1
                else:
                    unresolved_byte_list.insert(0, dict_rightch[compressed_byte])
                    unresolved_byte_list.insert(0, dict_leftch[compressed_byte])

        if compressed_file.tell() % 4 != 0:
            compressed_file.seek(compressed_file.tell() + (4 - compressed_file.tell() % 4))

    end_block_offset = compressed_file.tell() - 4

    return start_block_offset, end_block_offset, subfile_start


def _compress_block(block, comp_block_list, attempt_num, is_subfile=False,
                    mod_mode=False, sort_order=None, new_sort_list=None):
    """
    BPE compresses block of data.

    This helper function for _compression handles the actual logic for
    compressing block of data in _compression().

    Function goes through uncompressed data block and counts occurrences
    of byte pairs, iteratively replacing byte pairs with their assigned
    keys and recounting until all keys are filled. Once the dictionary is
    built, it is converted into a series of byte instructions and the
    compressed data is appended to the instructions. The full compressed
    block is lastly appended to a list of compressed blocks.

    Parameters
    ----------
    block : list
        Contains block #, block size, and block data.
    comp_block_list : list
        List of (block #, block size, compressed block) tuples.
    attempt_num : int
        Number of current compression attempt for _choose_sort().
    is_subfile : bool
        Flag indicating whether file is a BPE file, or a non-BPE file
        that contains BPE-compressed data within its body. (default: False)
    mod_mode : bool
        Flag indicating the file is being compressed for a mod and compressed
        size needs to be no larger than the original. (default: False)
    sort_order : int
        Number indicating how to sort compression block, if it's been previously
        sorted successfully. (default: None)
    new_sort_list : list
        List of tuples containing block number and sort order, if a sort
        order already exists. (default: None)
    """

    if new_sort_list is None:
        new_sort_list = []

    # Build the initial dictionary/lookup table. The left-character dict
    # is filled so that each key contains itself as a value, while the
    # right-character dict is filled with empty values.
    dict_leftch = {x: '' for x in range(0x100)}
    dict_rightch = dict_leftch.copy()

    # Add each unique byte found in block to dict_leftch.
    curr_block = block[2]
    for byte in curr_block:
        if byte not in dict_leftch.values():
            dict_leftch[byte] = byte

    # Create sorted list of unfilled keys available to hold byte pairs.
    empty_keys = sorted([key for key in dict_leftch.keys()
                         if dict_leftch[key] == '' and key != 0xff])
    last_empty_key = empty_keys[-1]

    bp_count_dict = {}  # Dict to keep track of how often each byte pair occurs.

    # Select integer indicating how byte pairs should be sorted when filling
    # the byte-pair dicts. If a sort order already exists, use that.
    sort_order = sort_order if sort_order is not None else _choose_sort(attempt_num)
    if mod_mode or is_subfile:
        # Add tuple of block number and sort order int to new_sort_list.
        # Used if no sort list was present from metadata.
        new_sort_list.append((block[0], sort_order))

    # Add byte pairs to empty keys in dictionaries.
    while True:
        # Count instances of each byte pair.
        for i, byte in enumerate(curr_block):
            try:
                byte_pair = (byte, curr_block[i + 1])
            except IndexError:
                break

            if byte_pair not in bp_count_dict.keys():
                bp_count_dict[byte_pair] = 1
            else:
                bp_count_dict[byte_pair] += 1

        bp_count_list = _sort_keys(bp_count_dict, sort_order)

        # Add most frequent byte pair to dictionaries and replace in block
        # with key value. Byte pairs are only added to the dictionary if
        # they occur at least 5 times and there are still unfilled keys
        # in the dicts. Values are replaced because compression is multi-pass
        # and byte pairs and pair counts must be recalculated each time.

        # TODO: Look into using ByteArray or ByteIO instead of doing
        #  a str.replace on an immutable byte string.
        if bp_count_list[0][1] >= 5 and empty_keys:
            empty_key = empty_keys.pop(-1)
            dict_leftch[empty_key] = bp_count_list[0][0][0]
            dict_rightch[empty_key] = bp_count_list[0][0][1]
            byte_pair = b''.join(x.to_bytes(1, 'big') for x in bp_count_list[0][0])
            curr_block = curr_block.replace(byte_pair, empty_key.to_bytes(1, 'big'))
            bp_count_dict = {}
        else:
            break

    key_list = sorted(dict_rightch.keys())
    comp_block = []
    previous_key = 0
    header, byte_pair = b'', b''

    # Find either first byte pair or use 0x80 literal. If the latter, assign
    # \xfe as header and /x7f as the first byte pair/literal. If a byte pair
    # found before 0x80, calculate header and get byte pair from dicts.
    for key in key_list:
        if dict_rightch[key] != '' and key <= 0x7f:
            header = (key + 0x7f).to_bytes(1, 'big')
            byte_pair = b''.join(x.to_bytes(1, 'big') for x in
                                 (dict_leftch[key], dict_rightch[key]))
            previous_key = key
            break
        elif key == 0x80:
            header = b'\xfe'
            byte_pair = b'\x7f'
            previous_key = key - 1
            break
    comp_block.append(header)
    comp_block.append(byte_pair)

    i = previous_key + 1
    sequential_key_run = False
    sequential_keys = 0
    while i <= last_empty_key:
        byte = dict_rightch[i]
        if byte != '' and i - previous_key > 1:
            # If the current key corresponds to a byte pair and there is a >1
            # key gap between the current and previous byte-pair key, then set
            # the number of sequential keys to 0 and calculate the header byte.
            # Then add the byte pair to the list of compressed bytes in order,
            # set previous_key to the current one, and increment the key.
            sequential_keys = 0
            header = (i + 0x7f - (previous_key + 1)).to_bytes(1, 'big')
            comp_block.append(header)
            left_byte = dict_leftch[i - sequential_keys].to_bytes(1, 'big')
            comp_block.append(left_byte)
            try:
                right_byte = dict_rightch[i - sequential_keys].to_bytes(1, 'big')
                comp_block.append(right_byte)
            except AttributeError as e:
                # I don't remember why this was necessary, but I'm sure it's
                # important for something.
                print(dict_leftch[i], dict_rightch[i])
                print(curr_block)
                raise e
            previous_key = i
            i += 1
        elif byte != '' and i - previous_key == 1:
            # If the current key corresponds to a byte pair and immediately
            # follows another byte pair, then a) set sequential_key_run to
            # true if it's not, b) increment sequential keys if the key two
            # keys later does not exceed dictionary size and the next two
            # keys contain byte pairs, or c) append the number of sequential
            # keys to the compressed data, followed by that number of keys'
            # bytes/byte pairs in sequence.
            if not sequential_key_run:
                sequential_key_run = True
            elif i + 2 < 256 \
                    and (not (dict_rightch[i + 1] == '' and dict_rightch[i + 2] == '')):
                sequential_keys += 1
                previous_key = i
                i += 1
            else:
                comp_block.append(sequential_keys.to_bytes(1, 'big'))
                while sequential_keys >= 0:
                    left_byte = dict_leftch[i - sequential_keys].to_bytes(1, 'big')
                    comp_block.append(left_byte)
                    if dict_rightch[i - sequential_keys] != '':
                        right_byte = dict_rightch[i - sequential_keys].to_bytes(1, 'big')
                        comp_block.append(right_byte)
                    sequential_keys -= 1
                sequential_keys = 0
                sequential_key_run = False
                previous_key = i
                i += 1
        elif byte == '' and sequential_key_run:
            # If the key contains a byte literal rather than byte pair
            # and a sequential_key_run is active, increment the number of
            # sequential keys.
            sequential_keys += 1
            previous_key = i
            i += 1
        else:  # Move on to next key.
            i += 1

    if all(val == '' for val in dict_rightch.values()):
        comp_block.append(b'\xfe\xff')  # For when dictionary contains only literals.
    else:
        comp_block.append((0x100 - (last_empty_key + 1) + 0x7f).to_bytes(1, 'big'))

    # Add decompression in front of compressed data block.
    curr_block = b''.join((b''.join(comp_block), curr_block))

    size = len(curr_block)
    padding = 4 - (size % 4) if size % 4 else 0
    curr_block = b''.join((curr_block, b'\x8c' * padding))
    block[2] = curr_block

    comp_block_list.append(block)


def _compress(decompressed_file, compressed_file, attempt_num=0,
              mod_mode=False, is_subfile=False):
    """
    BPE compresses LoD game files.

    Compresses decompressed files into BPE files using metadata created by
    _decompress(). Each block is compressed individually (asynchronously if
    >15 blocks are being compressed), and blocks are ordered and written to
    the compressed file at the end.

    Anything added to an uncompressed file that increases its size should
    be added to end of file so as not to mess up pointers. Therefore,
    original block sizes of the compressed file can be used, adding new
    blocks to the end as needed. Note that this will not work for all files,
    as often the game will load data into RAM offsets immediately after some
    files (S_ITEM.OV_, for example).

    Parameters
    ----------
    decompressed_file : BufferedReader
        I/O file object of decompressed file.
    compressed_file : str
        Name of compressed file.
    attempt_num : int
        Number of current compression attempt for _choose_sort(). (default: 0)
    mod_mode : bool
        Flag indicating the file is being compressed for a mod and compressed
        size needs to be no larger than the original. (default: False)
    is_subfile : bool
        Flag indicating whether file is a BPE file, or a non-BPE file
        that contains BPE-compressed data within its body. (default: False)

    Returns
    -------
    tuple (int, int, list, str)
        Tuple containing end block offset, new end offset, the updated sort
        order list, and the compressed file name.
    """

    file_name = os.path.realpath(decompressed_file.name)
    meta_file = os.path.join(os.path.dirname(file_name), 'meta',
                             os.path.basename(file_name))
    backup_file(compressed_file)

    # Adds byte pairs to dictionary until no pairs exist with count >= 5
    # or no empty keys are left.
    # Get the original decompressed file size, start block, end block, and
    # original block sizes from the metadata file. Once all block sizes have
    # been read, if sort order data is present from a previous compression,
    # read sort order bytes ones at a time into a list as ints.
    with open(meta_file, 'rb') as inf:
        orig_file_size = int.from_bytes(inf.read(4), 'little')
        start_block = int.from_bytes(inf.read(2), 'little')
        end_block = int.from_bytes(inf.read(2), 'little')

        blocksize_list = []
        while True:
            blocksize = inf.read(4)
            if blocksize != b'\xff' * 4:
                blocksize_list.append(int.from_bytes(blocksize, 'little'))
            else:
                sort_order_list = []
                while True:
                    sort_num = inf.read(1)
                    if sort_num != b'':
                        sort_order_list.append(int.from_bytes(sort_num, 'little'))
                    else:
                        break
                break

    # Perform a "fake" decompression of compressed file to get the offsets
    # of the start and end blocks. Necessary because compressor is naive to
    # any changes in compressed file size or block offset potentially created
    # by previous compressions. Does not create a decompressed file.
    # TODO: Find way get start/end block offsets without decompression.
    #  This method may be unnecessary, and could potentially be replaced
    #  by pattern searching (b'[\x00-\xff][\x00-\x08]\x00\x00') on only word-
    #  aligned values. However, testing is required, as it is possible this
    #  pattern can appear in situations where it is not a block size.
    with open(compressed_file, 'rb+') as comp:
        start_block_offset, end_block_offset, subfile_start = \
            _dummy_decompress(comp, start_block, end_block, is_subfile)

        # Read any data after the end block offset to memory, then truncate
        # the file to the start block offset.
        comp.seek(end_block_offset)
        comp_file_end = comp.read()
        comp.truncate(start_block_offset)
        if is_subfile:
            comp.seek(subfile_start)
        else:
            comp.seek(0)

        # Calculate and write the new uncompressed file size.
        file_size = os.path.getsize(decompressed_file.name)
        if file_size != orig_file_size:
            size_diff = file_size - orig_file_size
        else:
            size_diff = 0
        full_file_size = int.from_bytes(comp.read(4), 'little')
        full_file_size += size_diff
        comp.seek(comp.tell()-4)
        comp.write(full_file_size.to_bytes(4, 'little'))

        comp.flush()

        comp.seek(start_block_offset)
        block_num = 0
        block_list = []
        while True:
            # Read the next block of bytes. If the uncompressed data exceeds
            # the original number of blocks, read overflow data in 0x800-byte
            # blocks
            if block_num >= len(blocksize_list) - 1:
                block = decompressed_file.read(0x800)
            else:
                block = decompressed_file.read(blocksize_list[block_num])
            block_num += 1  # TODO: Is this really where this should iterate?

            uncompressed_blocksize = len(block)
            if uncompressed_blocksize == 0:
                break
            else:
                # Append list to block list that contains the block # (for sorting),
                # the uncompressed size of the block, and the block data.
                block_list.append(
                    [block_num, uncompressed_blocksize.to_bytes(4, 'little'), block])

        random.seed()  # Random seed for block sort order.

        # Use a multiprocessing Pool to compress blocks simultaneously if there
        # are more than 15 blocks to compress. Less than that and the extra time
        # taken to create the pool tends to exceed benefits of multiprocessing.
        # This inflection point could probably be better chosen with further
        # testing. the arguments used for _compress_block() depend on the
        # values of mod_mode, is_subfile, and sort_order_list.
        if len(block_list) > 15:
            pool = multiprocessing.Pool(multiprocessing.cpu_count() - 1 or 1)
            manager = multiprocessing.Manager()  # Manager lists necessary for async.
            comp_block_list = manager.list()
            new_order_list = manager.list()
            for i, b in enumerate(block_list):
                if (mod_mode or is_subfile) and sort_order_list:
                    pool.apply_async(_compress_block, args=(b, comp_block_list, attempt_num,
                                                            is_subfile, mod_mode,
                                                            sort_order_list[i]))
                elif mod_mode or is_subfile:
                    pool.apply_async(_compress_block, args=(b, comp_block_list, attempt_num,
                                                            is_subfile, mod_mode, None,
                                                            new_order_list))
                else:
                    pool.apply_async(_compress_block, args=(b, comp_block_list, attempt_num))
            pool.close()
            pool.join()

            # Convert the manager list objects to normal lists.
            comp_block_list = [item for item in comp_block_list]
            new_order_list = [item for item in new_order_list]
        else:
            comp_block_list = []
            new_order_list = []
            for i, b in enumerate(block_list):
                if (mod_mode or is_subfile) and sort_order_list:
                    _compress_block(b, comp_block_list, attempt_num, is_subfile, mod_mode=mod_mode,
                                    sort_order=sort_order_list[i], new_sort_list=[])
                elif mod_mode or is_subfile:
                    _compress_block(b, comp_block_list, attempt_num, is_subfile, mod_mode=mod_mode,
                                    new_sort_list=new_order_list)
                else:
                    _compress_block(b, comp_block_list, attempt_num)

        # Sort the compressed block list and sort order lists, then write
        # the block sizes and compressed block data to the compressed file.
        # Once all blocks are written, write the post-block range data.
        comp_block_list.sort(key=lambda x: x[0])
        new_order_list.sort(key=lambda x: x[0])
        for b in comp_block_list:
            comp.write(b[1])
            comp.write(b[2])
        new_end_offset = comp.tell()
        comp.read(4)
        comp.write(comp_file_end)

    return end_block_offset, new_end_offset, new_order_list, compressed_file


def run_compression(decompressed_file, mod_mode=True, is_subfile=False,
                    max_attempts=100, delete_decompressed=False):
    """
    Wrapper function for _compress().

    When a file is being compressed normally, the function calls _compress()
    once and writes the new file. However, if the file is a subfile (as in
    SCUS for example), or is intended for creating or applying a mod,
    additional logic is required. _compress() will be called until the new
    compressed size is no larger than the original, or the maximum number
    of attempts specified is reached. Each time _compress() is used, the
    byte pairs in the blocks will be sorted in a different order in an
    attempt to minimize compression size.

    Note: Although individual or ranges of blocks can be decompressed/
    compressed, it is advised to simply decompress/compress the entire
    file at once, as this will permit compatibility with other mods.

    Parameters
    ----------
    decompressed_file : str
        Name of file to compress.
    mod_mode : bool
        Flag indicating the file is being compressed for a mod and compressed
        size needs to be no larger than the original. (default: False)
    is_subfile : bool
        Flag indicating whether file is a BPE file, or a non-BPE file
        that contains BPE-compressed data within its body. (default: False)
    max_attempts : int
        Maximum number of times to attempt to compress a file. (default: 100)
    delete_decompressed : bool
        Flag indicating whether to delete decompressed file after compression.
    """

    print('Compress: Compressing file %s' % decompressed_file)
    if not os.path.isfile(decompressed_file):
        print('Compress: %s does not exist' % decompressed_file)
        print('Compress: Skipping file')
        return

    # Since compression requires a clean copy of the file, a temp copy
    # is created to replace the main file following failed compressions
    # (size limit not achieved). This is done rather than using the clean
    # backup so that already-modded files can be compressed without losing
    # previous changes.
    meta_file = os.path.join(os.path.dirname(decompressed_file), 'meta',
                             os.path.basename(decompressed_file))
    extension = os.path.splitext(decompressed_file)[1]
    compressed_dir = os.path.dirname(decompressed_file)
    compressed_file = os.path.join(
        os.path.dirname(compressed_dir),
        os.path.basename(compressed_dir).replace('_dir', extension))
    temp = '.'.join((compressed_file, 'temp'))
    shutil.copy(compressed_file, temp)

    with open(decompressed_file, 'rb') as inf:
        if is_subfile or mod_mode:
            attempts = 1
            print('Compress: Attempting to compress file to original size.')
        else:
            attempts = 0

        return_vals = None
        while True:
            if is_subfile or mod_mode:
                if attempts == 1:
                    print('Compress: Attempt %d/%d' % (attempts, max_attempts))
                else:
                    print('Compress: Attempt %d/%d (Prev: [original size: %d, new size: %d])' %
                          (attempts, max_attempts, return_vals[0], return_vals[1]))

            # Compress file.
            return_vals = _compress(inf, compressed_file, attempts, mod_mode, is_subfile)

            # If file is not a subfile and not flagged for modding, no further action
            # is necessary. If either of those are true, however, further action is
            # necessary if the new compressed size is greater than the original
            # compressed size. If the max number of attempts has not been reached,
            # compression will be attempted until compressed size is no more than
            # original. If max attempts is reached, the function will print a warning
            # and return.
            #
            # Once an appropriate size is achieved, the sort order list will be
            # written out to the metadata file. If the compressed file is a subfile
            # (as found in SCUS/SCES/SCPS and S_BTLD), some additional actions are
            # performed to write the post-compression data to the correct location.
            if (is_subfile or mod_mode) and return_vals[0] < return_vals[1] and \
                    ((os.path.getsize(decompressed_file) > 0x800 and attempts < max_attempts) or
                     (os.path.getsize(decompressed_file) <= 0x800 and attempts <= 5)):
                attempts += 1
                shutil.copy(temp, compressed_file)
                inf.seek(0)
                continue
            elif (is_subfile or mod_mode) and return_vals[0] < return_vals[1] and \
                    ((os.path.getsize(decompressed_file) > 0x800 and attempts >= max_attempts) or
                     (os.path.getsize(decompressed_file) <= 0x800 and attempts > 5)):
                shutil.copy(temp, compressed_file)
                os.remove(temp)
                print('Compress: Could not compress subfile to original size')
                print('Compress: Compression terminated')
                return
            else:
                if is_subfile or mod_mode:
                    with open(meta_file, 'rb+') as outf:
                        while True:
                            if outf.read(4) == (b'\xff' * 4):
                                break
                        for num in return_vals[2]:
                            outf.write(num[1].to_bytes(1, 'little'))

                if is_subfile and return_vals[1] < return_vals[0]:
                    with open(return_vals[3], 'rb+') as f:
                        data = b''
                        if 'SCUS' in decompressed_file.upper()\
                                or 'SCES' in decompressed_file.upper()\
                                or 'SCPS' in decompressed_file.upper():
                            f.seek(0x36c28 - (return_vals[0] - return_vals[1]))
                            data = f.read()
                            f.seek(0x36c28 - (return_vals[0] - return_vals[1]))
                        elif 'BTLD' in decompressed_file.upper():
                            f.seek(0x68d8 - (return_vals[0] - return_vals[1]))
                            data = f.read()
                        f.write(b'\x00' * (return_vals[0] - return_vals[1]))
                        f.write(data)

                print('Compress: File compressed')

            break

    # Delete the temp file, and the decompressed file as well if specified.
    os.remove(temp)
    if delete_decompressed:
        shutil.rmtree(os.path.dirname(decompressed_file))


# MRG handling and file swapping functions + integrated functions

class LBATable:
    """
    A class for storing necessary values from the logical block addressing
    tables at the beginnings of MRG files.

    Functions
    ---------
    read_lba_table()
        Reads MRG LBA table to LBATable object.

    Attributes
    ----------
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
    num_files : int
        Number of files contained in MRG file (excludes LBA); defined by
        second 4-byte word header.
    lba_table_len : int
        Length of the LBA table; equal to num_files * 8
    ptr_locs = int list
        List containing offsets of all 8-byte entries in LBA table.
    file_locs = int list
        List containing offsets of all files in MRG, as defined by first
        4 bytes of each LBA table entry.
    file_sizes : int list
        List containing sizes of all files in MRG, as defined by second
        4 bytes of each LBA table entry.
    """

    def __init__(self, source_file, sector_padding):
        """
        Parameters
        ----------
        source_file : BufferedReader
            MRG file that files are being extracted from/inserted into
        sector_padding : bool
            Value stating whether the MRG file uses '0x8c' sector padding.
        """

        source_file.seek(4)
        self.sector_padding = sector_padding
        self.num_files = int.from_bytes(source_file.read(4), 'little')
        self.lba_table_len = self.num_files * 0x08
        self.ptr_locs = []
        self.file_locs = []
        self.file_sizes = []

    def __len__(self):
        return len(self.ptr_locs)

    def read_lba_table(self, source_file):
        """
        Reads MRG LBA tables and stores values.

        Loops through all 8-byte entries of MRG LBA table, and appends pointer
        offsets, pointer values/file offsets, and file sizes to their respective
        list variables, then co-sorts all lists.

        Parameters
        ----------
        source_file : BufferedReader
            MRG file that files are being extracted from/inserted into
        """

        source_file.seek(0x08)

        for file_num in range(self.num_files):
            self.ptr_locs.append(source_file.tell())

            loc = int.from_bytes(source_file.read(4), 'little')
            if self.sector_padding:
                # Pointer values are multiplied by 0x800 if pointer values
                # are sector numbers rather than actual offsets.
                loc = loc * 0x800
            self.file_locs.append(loc)

            size = source_file.read(4)
            self.file_sizes.append(int.from_bytes(size, 'little'))

        self.file_locs, self.file_sizes, self.ptr_locs = \
            sort_together(
                [self.file_locs, self.file_sizes, self.ptr_locs], key_list=(0, 1))
        self.file_locs, self.file_sizes, self.ptr_locs = \
            list(self.file_locs), list(self.file_sizes), list(self.ptr_locs)


def parse_input(file_list, num_files_in_mrg):
    """
    Parses file list input and returns list of file numbers.

    Function interprets file list input and returns it in form
    usable by extraction/insertion functions. Function accepts
    list containing '*' (all files), '^' (references parent file,
    skipped by extraction/insertion functions), 'int', and 'int-int'
    (integer range).

    Parameters
    ----------
    file_list : str list
        Takes a list of strings from either command line or the
        extract/insert_all_from_list functions as files to
        extract/insert.
    num_files_in_mrg : int
        Number of files in the source MRG file. Used when '*' is
        in file_list.

    Returns
    -------
    int list
        Integer list of all files to extract/insert.
    """
    num_list = set()
    for item in file_list:
        try:
            m1 = re.match(r'(\d+)(?:-(\d+))?$', item[0])
            m2 = re.match(r'(\*)?$', item[0])
            m3 = re.match(r'(\^)?$', item[0])

            if m3:
                continue
            elif not m1 and not m2:
                raise TypeError
            elif m1 and not m2:
                start = m1.group(1)
            else:
                start = m2.group(1)

            if start == '*':
                num_list.update(range(1, num_files_in_mrg + 1))
            else:
                end = m1.group(2) or start
                num_list.update(range(int(start), int(end) + 1))
        except TypeError:
            print(('Parse: \'' + item[0] + '\' not a positive int or range'
                   ' (e.g. 0-5). Skipping argument.'))
            continue

    return sorted(list(num_list))


def extract_files(source_file, sector_padding=False, files_to_extract=('*',)):
    """
    Extracts files from MRG files.

    Extracts all specified files from source MRG file to separate files
    in subdirectory, using offset/size pairs in the LBA table. If '*' is
    given for files_to_extract, all files are extracted. Otherwise, only
    the individual files specified are extracted. File numbering starts
    at 1. File 0 corresponds to the LBA table, and is excluded from '*'.

    Parameters
    ----------
    source_file : string
        Path and name of file that files are being extracted from.
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
        Default: False
    files_to_extract : list
        List of files to extract. Default: ('*',) [all files excluding
        file 0 {the LBA table}]
    """

    # Return if file does not exist or file size is 0.
    if not os.path.isfile(source_file):
        print('Extract: File %s not found' % source_file)
        print('Extract: Skipping file')
        return
    elif not os.path.getsize(source_file):
        print('Extract: %s is an empty file' % source_file)
        print('Extract: Skipping file')
        return

    with open(source_file, 'rb') as inf:
        # Check that file is MRG file. Return if not.
        header = inf.read(4)
        if header != b'MRG\x1a':
            print('Extract: %s is not a MRG file' % source_file)
            print('Extract: Skipping file')
            return

        print('Extract: Extracting files from %s' % source_file)

        # Read LBA table
        lba_list = LBATable(inf, sector_padding)
        if lba_list.num_files == 0:
            return
        lba_list.read_lba_table(inf)

        # Get list of files to extract. Return if empty.
        file_nums = parse_input(files_to_extract, lba_list.num_files)
        if not file_nums:
            return  # Exit function early if no files to extract.

        # Create output directory
        output_dir = '_'.join((os.path.splitext(source_file)[0], 'dir'))
        os.makedirs(output_dir, exist_ok=True)
        basename = os.path.splitext(os.path.basename(source_file))[0]

        # Loop through all items in file_nums. For each, go to the offset
        # corresponding to the file number, read file size bytes, and write
        # them to a new file.
        files_extracted = 0
        for num in file_nums:
            # Creates a file 0 containing LBA table. Not especially useful.
            if num == 0:
                file_loc = 0
                file_size = lba_list.lba_table_len + 8
            else:
                # Make sure source actually contains file number
                try:
                    file_loc = lba_list.file_locs[num-1]
                    file_size = lba_list.file_sizes[num-1]
                except IndexError:
                    print('Extract: File %d does not exist. '
                          '%s contains %d files' %
                          (num, source_file, len(lba_list)))
                    print('Extract: Skipping file')
                    continue

            output_file = os.path.join(
                output_dir, ''.join((basename, '_', str(num), '.bin')))

            with open(output_file, 'wb') as outf:
                inf.seek(file_loc)
                outf.write(inf.read(file_size))

            files_extracted += 1
        else:
            print('Extract: Extracted %d of %d files' %
                  (files_extracted, len(file_nums)))


def _extraction_handler(source_file, sector_padding=False, files_to_extract=('*',)):
    """
    Wrapper function for extracting/decompressing files when using
    extract_all_from_list.

    A wrapper function that calls either run_decompression (on OV_, SCUS/SCES/
    SCPS, and some DRGN0 files with BPE compression) or extract_files
    (on MRG files). This serves as a helper function for extract_all_from_list
    to handle how each entry in the file list text file is dealt with.

    Parameters
    ----------
    source_file : string
        Path and name of file that files are being extracted from. Is either
        a MRG file that files are being extracted from, or a BPE file that is
        being decompressed.
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
        The negation of this variable also serves as an indication of whether
        a compressed file is a main file or a subfile within another file.
        Default: False
    files_to_extract : list
        List of files to extract (MRG) or blocks to decompress (BPE).
        Default: ('*',) [all files excluding file 0 of MRG files {the LBA table}]
    """

    # Exit function if file number is '^', which references parent file.
    if any('^' in sl[0] for sl in files_to_extract):
        return

    if not os.path.exists(source_file):
        print('Extract: %s does not exist' % source_file)
        return

    source_file = source_file.upper()
    with open(source_file, 'rb') as f:
        mrg = f.read(4)
        bpe = f.read(4)

    # extract_files() is used for all MRG files. Checked first since
    # some MRGs contain BPEs.
    # run_decompression() is used for BPE files. Condition checks for
    # OV_ and SCUS/SCES/SCPS as well as BPE header because certain of
    # these files have BPE subfiles where the header occurs later.
    if re.match(b'MRG\x1a', mrg):
        extract_files(source_file, sector_padding, files_to_extract)
    elif re.match(b'BPE\x1a', bpe) \
            or ('OV_' in source_file or 'SCUS' in source_file
                or 'SCES' in source_file or 'SCPS' in source_file):
        for i in files_to_extract:
            if i[0] == '*':
                block_segment = (0, 512)
            elif '-' not in i[0]:
                block_segment = (int(i[0]), 512)
            else:
                block_segment = [int(x) for x in (i[0].split('-'))]

            run_decompression(source_file, block_segment[0],
                              block_segment[1], not sector_padding)
    else:
        print('Extract: %s is not a MRG or BPE file' % source_file)
        print('Extract: Skipping file')


def extract_all_from_list(list_file, disc_dict, file_category='[ALL]'):
    """
    Extracts all files specified by the file list txt file given in the config.

    Reads the list_file txt file into a dictionary for use with
    _extraction_handler(), which is called for every source file in the dict.
    Each source file is then extracted from (MRG) or decompressed (BPE).

    Parameters
    ----------
    list_file : str
        Text file containing list of source files to extract from/decompress.
    disc_dict : dict
        Dict containing information about disc image, directory structure,
        and game files
    file_category : str
        The header category containing file entries to extract from/decompress.
        Values are '[PATCH]', '[SWAP]', and '[ALL]'.
        Default: '[ALL]'
    """

    # '[ALL]' will read the file entries in both the [PATCH] and [SWAP]
    # categories of the file list txt file. Each category can also be
    # specified individually.
    is_insert = False
    files_dict = read_file_list(list_file, disc_dict, reverse=is_insert, file_category=file_category)

    # Call _extraction_handler() on each file entry for each disc for each
    # category (i.e. [PATCH]).
    print('\nExtract: Extracting files\n')
    for cat, cat_val in files_dict.items():
        for disc, disc_val in cat_val.items():
            for key in sorted(disc_val.keys(), key=numerical_sort):
                _extraction_handler(key, disc_val[key][0], disc_val[key][1:])

    print('\nExtract: Complete')


def insert_files(source_file, sector_padding=False, files_to_insert=('*',),
                 del_subdir=False):
    """
    Inserts subfiles into MRG files.

    Inserts all specified files located in subdirectory into source
    MRG file, using offset/size pairs in the LBA table. If '*' is
    given for files_to_insert, MRG file is fully rebuilt, rather than
    inserting all files normally (this performs faster on larger files,
    particularly when some subfiles are increased in size). All files
    must be in the subdirectory for this to work. If individual files
    are specified, only those files are inserted. File numbering starts
    at 1. File 0 corresponds to the LBA table, and is ignored, as the
    LBA table in the source file is used instead. The file subdirectory
    can optionally be deleted after insertion is complete.

    Parameters
    ----------
    source_file : string
        Path and name of file that files are being inserted into.
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
        Default: False
    files_to_insert : list
        List of files to insert. Default: ('*',) [all files in
        subdirectory, excluding 0 {the LBA table}]
    del_subdir : bool
        Specifies whether to delete subdirectory containing component
        files. Default: False
    """

    # Return if file does not exist or file size is 0.
    if not os.path.isfile(source_file):
        print(f'Insert: File {source_file} not found')
        print('Insert: Skipping file')
        return
    elif not os.path.getsize(source_file):
        print(f'Insert: {source_file} is an empty file')
        print('Insert: Skipping file')
        return

    # TODO: Because of stuff like this, should probably always be calling
    #  insert_all even for single files, but that's restructuring for the
    #  C# version
    backup_file(source_file, True if files_to_insert[0] == '*' else False, True)
    with open(source_file, 'rb+') as outf:
        # Check that file is MRG file. Return if not.
        header = outf.read(4)
        if header != b'MRG\x1a':
            print(f'Insert: {source_file} is not a MRG file')
            print('Insert: Skipping file')
            return

        print(f'Insert: Inserting files into {source_file}')

        input_dir = '_'.join((os.path.splitext(source_file)[0], 'dir'))
        basename = os.path.splitext(os.path.basename(source_file))[0]

        # Read LBA table
        lba_list = LBATable(outf, sector_padding)
        lba_list.read_lba_table(outf)

        # Store first item in file list for rebuild test.
        all_files_test = files_to_insert[0]

        # Get list of files to insert. Return if empty.
        file_nums = parse_input(files_to_insert, len(lba_list.file_locs))
        if not file_nums:
            return

        # Exclude File 0 (LBA table) from insertion.
        if file_nums[0] == 0:
            file_nums = file_nums[1:]

        # If all files was specified, make sure that file numbers in
        # subdir match file numbers in LBA table. If they don't, set
        # all_files_test to '' so that _insert_helper() will be used
        # rather than _rebuild_helper. Non-existent files are left in
        # the list so that an error will print later to alert the user
        # of the issue.
        # TODO: Maybe move logic of non-existent files here
        if all_files_test == '*':
            subdir_check = sorted(
                [int(os.path.basename(os.path.splitext(x)[0]).split('_')[-1])
                 for x in glob.glob(os.path.join(input_dir.upper(), '*.bin'))])
            if file_nums != subdir_check:
                all_files_test = ''

        # If all files was specified and they exist in subdir, then rebuild
        # the files. Otherwise, files are inserted.
        if all_files_test == '*':
            files_inserted = _rebuild_helper(outf, lba_list, sector_padding,
                                             input_dir, basename)
        else:
            files_inserted = _insert_helper(outf, lba_list, file_nums,
                                            sector_padding, input_dir, basename)

        # Update LBA table with new file location and size values.
        for i in range(0, len(lba_list)):
            outf.seek(lba_list.ptr_locs[i])
            if sector_padding:
                outf.write(int.to_bytes((lba_list.file_locs[i] // 0x800), 4, 'little'))
            else:
                outf.write(int.to_bytes(lba_list.file_locs[i], 4, 'little'))
            outf.write(int.to_bytes(lba_list.file_sizes[i], 4, 'little'))
        else:
            print('Insert: Inserted %d of %d files' %
                  (files_inserted, len(file_nums)))

        # Attempt to delete subdirectory if del_subdir is true.
        try:
            if del_subdir:
                shutil.rmtree(input_dir)
        except PermissionError:
            print('Insert: Could not delete %s. Make sure that no files in folder '
                  'are in use' % input_dir)
        except FileNotFoundError:
            pass


def _insert_helper(src_file, lba_table, file_nums, sector_padding,
                   input_dir, basename):
    """
    Helper function to insert files individually into a MRG file.

    This helper function for insert_files() is used when all files ('*')
    is not specified, or it is but not all of the files exist in the
    subdirectory. It uses file_nums to access entries in the LBA table,
    goes to the offset indicated, and writes the corresponding subfile
    to that location. If the subfile exceeds the original file size (plus
    sector padding), the remainder of the file is read prior to insertion,
    then written back afterwards. The LBA table  object is updated with
    new file offsets and sizes.

    Parameters
    ----------
    src_file : BufferedReader
        MRG file that files are being inserted into.
    lba_table : LBATable
        LBA table of src_file.
    file_nums : int list
        List of files to be inserted into src_file, by file number.
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
    input_dir : string
        Subdirectory containing subfiles to be inserted into src_file.
    basename : string
        Base name of MRG file (e.g. DRGN21_43 for DRGN21_43.BIN).

    Returns
    -------
    int
        Count of files successfully inserted into MRG file.
    """

    # Loop through all items in file_nums. For each, go to the offset
    # corresponding to the file number and write the subfile to the
    # source file.
    files_inserted = 0
    for index, num in enumerate(file_nums):
        input_file = os.path.join(
            input_dir, ''.join((basename, '_', str(num), '.bin')))

        # Make sure source actually contains file number, and input
        # file exists. Skip file if not.
        if num > len(lba_table):
            print('Insert: File %s does not exist' %
                  input_file)
            print('Insert: Skipping file')
            continue
        if not os.path.isfile(input_file):
            print('Insert: File %s not found' % input_file)
            print('Insert: Skipping file')
            continue

        with open(input_file, 'rb') as inf:
            # Preferred behavior for insert_files() is to have inserted files
            # overwrite existing data if they are the same length as or
            # shorter than the original (including sector padding for files
            # that have it). If the file being inserted is longer, then the
            # end of the file is broken off, the inserted file is written in,
            # and the end of the source file is written back to the end and
            # the LBA entries are updated.
            file_size = os.path.getsize(input_file)
            if (num == len(lba_table)
                    or (file_size <= ceil(lba_table.file_sizes[num - 1] / 0x800) * 0x800
                        and sector_padding)
                    or (file_size <= ceil(lba_table.file_sizes[num - 1] / 4) * 4
                        and not sector_padding)):
                src_file.seek(lba_table.file_locs[num - 1])
                src_file.write(inf.read())

                # With the exception of the final subfile, any file that where
                # size % 4 != 0 is padded with 0x8c, even when the source file
                # is not sector padded.
                if not sector_padding and num != len(lba_table) \
                        and file_size % 4:
                    src_file.write(b'\x8C' * (0x04 - file_size % 0x04))
                src_file.flush()

                lba_table.file_sizes[num - 1] = file_size
            else:
                src_file.seek(lba_table.file_locs[num])
                data = src_file.read()
                src_file.seek(lba_table.file_locs[num - 1])
                src_file.write(inf.read())

                # As above, but also add sector padding when necessary.
                # Sector padding already exists in the source file for
                # sector-padded files that don't exceed the original sector.
                if not sector_padding and num != len(lba_table) \
                        and file_size % 4:
                    src_file.write(b'\x8C' * (0x04 - file_size % 0x04))
                elif sector_padding and file_size % 0x800:
                    src_file.write(b'\x8C' * (0x800 - file_size % 0x800))
                src_file.flush()  # flush to make sure tell() gives correct offset

                size_enlarged_by = src_file.tell() - lba_table.file_locs[num]
                src_file.write(data)
                src_file.flush()
                lba_table.file_sizes[num - 1] = file_size

                # Update file_locs following the file just written if file is larger
                # than the original.
                if size_enlarged_by > 0:
                    for i in range(num, len(lba_table)):
                        lba_table.file_locs[i] = \
                            lba_table.file_locs[i] + size_enlarged_by

        files_inserted += 1

    return files_inserted


def _rebuild_helper(src_file, lba_table, sector_padding, input_dir, basename):
    """
    Helper function to fully rebuild MRG file from subfiles.

    This helper function for insert_files() is used when all files ('*')
    is specified and all of the files exist in the subdirectory. It walks
    through the LBA table and writes each subfile in order, writing sector
    padding as necessary. The LBA table object is updated with new file
    offsets and sizes.

    Parameters
    ----------
    src_file : BufferedReader
        MRG file that is being rebuilt.
    lba_table : LBATable
        LBA table of src_file.
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
    input_dir : string
        Subdirectory containing subfiles to rebuild src_file from.
    basename : string
        Base name of MRG file (e.g. DRGN21_43 for DRGN21_43.BIN).

    Returns
    -------
    int
        Count of files successfully inserted into MRG file.
    """

    # Seek end of LBA table (plus sector padding if necessary)
    # and truncate file.
    if sector_padding:
        src_file.seek(src_file.tell() + 8 +
                      (0x800 - (src_file.tell() + 8) % 0x800))
    else:
        src_file.seek(lba_table.lba_table_len + 8)
    src_file.truncate()

    # Loop through each file, write it to the truncated src_file, and
    # update offset and size values in the LBATable.
    files_inserted = 0
    orig_file_loc = 0
    for file in range(1, lba_table.num_files+1):
        # Check is necessary due to several duplicate references to the
        # same 8-byte file. Makes sure that duplicate overwrites itself
        # instead of writing additional copies.
        if file > 1 and orig_file_loc == lba_table.file_locs[file-1]:
            src_file.seek(orig_file_loc)

        # Get original offset of current file and current offset in
        # src_file. If these are not the same, calculate the offset
        # difference and add that to the file offset in the LBATable.
        orig_file_loc = lba_table.file_locs[file-1]
        file_loc = src_file.tell()
        if file_loc != orig_file_loc:
            loc_diff = file_loc - orig_file_loc
            for i in range(file-1, lba_table.num_files):
                lba_table.file_locs[i] += loc_diff

        # Get size of subfile being inserted, update size in the LBATable,
        # then write the subfile to src_file, padding if necessary.
        input_file = os.path.join(
            input_dir, ''.join((basename, '_', str(file), '.bin')))
        with open(input_file, 'rb') as inf:
            file_size = os.path.getsize(input_file)
            lba_table.file_sizes[file-1] = file_size
            src_file.write(inf.read(file_size))
            src_file.flush()
            curr_offset = src_file.tell()
            if not sector_padding and file != lba_table.num_files \
                    and curr_offset % 4:
                src_file.write(b'\x8C' * (0x04 - curr_offset % 0x04))
            elif sector_padding and curr_offset % 0x800:
                src_file.write(b'\x8C' * (0x800 - curr_offset % 0x800))
            src_file.flush()
        files_inserted += 1

    return files_inserted


def _insertion_handler(source_file, sector_padding=False, files_to_insert=('*',),
                       del_subdir=False):
    """
    Wrapper function for inserting/compressing files when using
    insert_all_from_list().

    A wrapper function that calls either run_compression() (on OV_, SCUS/SCES/
    SCPS, and some DRGN0 files with BPE compression) or insert_files()
    (on MRG files). This serves as a helper function for insert_all_from_list()
    to handle how each entry in the file list text file is dealt with.

    Parameters
    ----------
    source_file : BufferedReader
        MRG file that files are being inserted into.
    sector_padding : bool
        Value stating whether the MRG file uses '0x8c' sector padding.
        Default: False
    files_to_insert : list
        List of files to insert. Default: ('*',) [all files in
        subdirectory, excluding 0 {the LBA table}]
    del_subdir : bool
        Specifies whether to delete subdirectory containing component
        files. Default: False
    """

    # Exit function if file number is '^', which references parent file.
    if any('^' in sl[0] for sl in files_to_insert):
        return

    if not os.path.exists(source_file):
        return

    source_file = source_file.upper()
    with open(source_file, 'rb') as f:
        mrg = f.read(4)
        bpe = f.read(4)

    # insert_files() is used for all MRG files.
    # Checked first since some MRGs contain BPEs.
    # run_compression() is used for BPE files. Condition checks for
    # OV_ and SCUS/SCES/SCPS as well as BPE header because certain of
    # these files have BPE subfiles where the header occurs later.
    if re.match(b'MRG\x1a', mrg):
        insert_files(source_file, sector_padding, files_to_insert, del_subdir)
    elif re.match(b'BPE\x1a', bpe) \
            or ('OV_' in source_file or 'SCUS' in source_file
                or 'SCES' in source_file or 'SCPS' in source_file):
        # Not restoring a clean file from backup may corrupt file
        backup_file(source_file, True, True)

        base_name = os.path.basename(source_file)
        bn_parts = os.path.splitext(base_name)
        for i in files_to_insert:
            block_range = process_block_range(i[0], base_name)
            dec_file = os.path.join(
                '_'.join((os.path.splitext(source_file)[0], 'dir')),
                ''.join((bn_parts[0], '_', block_range, bn_parts[1])))

            run_compression(dec_file, False, not sector_padding,
                            delete_decompressed=del_subdir)
            # TODO: need to come up with another method of specifying subfiles
            #  for compression because did not originally anticipate all the
            #  nested BPEs in DRGN0
    else:
        print(f'Insert: {source_file} is not a MRG or BPE file')
        print('Insert: Skipping file')


def insert_all_from_list(list_file, disc_dict, file_category='[ALL]',
                         del_subdir=False):
    """
    Inserts all files specified by the file list txt file given in the config.

    Reads the list_file txt file into a dictionary for use with
    _insertion_handler(), which is called for every source file in the dict.
    Each source file then has subfiles inserted into it (MRG) or decompressed
    block segments compressed into it (BPE).

    Parameters
    ----------
    list_file : str
        Text file containing list of files to insert/compress.
    disc_dict : dict
        Dict containing information about disc image, directory structure,
        and game files
    file_category : str
        The header category containing file entries to insert/compress into.
        Values are '[PATCH]', '[SWAP]', and '[ALL]'.
        Default: '[ALL]'
    del_subdir : bool
        Specifies whether to delete subdirectory containing component
        files (MRG) and decompressed files (BPE). Default: False
    """

    # '[ALL]' will read the file entries in both the [PATCH] and [SWAP]
    # categories of the file list txt file. Each category can also be
    # specified individually.
    is_insert = True
    files_list = read_file_list(list_file, disc_dict, reverse=is_insert, file_category=file_category)

    # Call _insertion_handler() on each file entry for each disc for each
    # category (i.e. [PATCH]).
    print('\nInsert: Inserting files\n')
    for cat, cat_val in files_list.items():
        for disc, disc_val in cat_val.items():
            for key in sorted(disc_val.keys(), key=numerical_sort, reverse=True):
                _insertion_handler(key, disc_val[key][0],
                                   disc_val[key][1:], del_subdir)

    print('\nInsert: Complete')


def unpack_all(source_file, sector_padded=False, delete_empty_files=False):
    """
    Fully unpacks a MRG file into all of its component files.

    This function recursively extracts all subfiles in the given source file.
    For each file, if it is a MRG/BPE, it is extracted/decompressed, then
    deleted from the source file's subfile directory. The function continues
    until it makes one full pass recursively walking the subfile directory
    without encountering a MRG/BPE file.

    The purpose of this function is to disassemble the DRGN0 and DRGN2x files
    to their lowest-level file components so that file types (e.g. TIMs, text)
    can be identified, and a file list txt file created so that they can be
    easily extracted in the future. Because MRG/BPE files are removed, the
    disassembled files cannot be re-inserted.

    Parameters
    ----------
    source_file : str
        Name of file to be unpacked.
    sector_padded : bool
        Whether the file being unpacked is sector aligned (default: False).
    delete_empty_files : bool
        Whether to delete files less than 8 bytes long (default: False).
    """

    # Check that source file exists and contains data.
    if not os.path.isfile(source_file):
        print('Unpack: %s does not exist' % source_file)
        print('Unpack: Skipping file')
        return
    elif not os.path.getsize(source_file):
        print('Unpack: %s is an empty file.' % source_file)
        print('Unpack: Skipping file')
        return

    # Extract top-level files from MRG, and set subfile directory to search.
    extract_files(source_file, sector_padded)
    dir_to_search = os.path.join(
        os.path.dirname(source_file),
        '_'.join((os.path.splitext(os.path.basename(source_file))[0], 'dir')))

    # Loop through subfile directory and extract/decompress all MRG/BPE files,
    # recursing through all subdirectories until no MRG/BPE files remain.
    while True:
        finished = True  # Assumes unpack will finish in one iteration.

        # List out all files in directory being searched and loop through them.
        file_list = [os.path.join(dp, f) for dp, dn, fn in
                     os.walk(dir_to_search) for f in fn]
        for file in file_list:
            # Delete all empty files.
            if delete_empty_files and os.path.getsize(file) <= 8:
                os.remove(file)
                continue

            # Read the header of the file.
            with open(file, 'rb') as f:
                print(f.name)
                header = f.read(8)

            # If the file is a MRG, extract all subfiles, then delete the
            # file and set finished to False. If the file is a BPE, decompress
            # it, then delete both file and metadata directory and set finished
            # to False. Otherwise, continue to next file.
            if MRG_FLAG.match(header):
                extract_files(file)
                os.remove(file)
                finished = False
            elif BPE_FLAG.match(header):
                run_decompression(file)
                os.remove(file)
                bpe_subdir = '_'.join((os.path.splitext(file)[0], 'dir'))
                shutil.rmtree(os.path.join(bpe_subdir, 'meta'))
                finished = False
            else:
                continue

        # Once no more MRGs or BPEs are encountered when looping through file_list,
        # exit the while loop.
        if finished:
            break

    # Delete all empty subdirectories.
    for f in sorted(glob.glob(os.path.join(dir_to_search, '**', '*'), recursive=True), reverse=True):
        try:
            os.rmdir(f)
        except OSError:
            pass


def file_swap(src_file, dst_file):
    """
    Replace file in game version being modded with same file from a
    different game version.

    Backs up the target version's file and then copies source version's
    copy of that file to the target.

    Parameters
    ----------
    src_file : string
        File from source version of the game replacing the file in the
        version being modded.
    dst_file : string
        File in target game version (the one being modded) that will be
        replaced.
    """

    try:
        backup_file(dst_file, hide_print=True)
        shutil.copy(src_file, dst_file)
    except FileNotFoundError:
        file = sys.exc_info()[1].filename
        print('Swap: File %s not found.' % file)
        raise FileNotFoundError
    except shutil.SameFileError:  # Ignore that files share the same name
        pass


def swap_all_from_list(list_file, disc_dict_pair, del_src_dir=False):
    """
    Replaces all files specified by the file list txt file given in the config
    with the same file from a different game version.

    Reads the [SWAP] section of the list_file txt file into a pair of dicts:
    one for the source game version and one for the target game version. For
    each file that is flagged as a moddable file, calls file_swap() to copy
    the version of the file from the source game's directory over the target
    version's copy of the same file.

    Parameters
    ----------
    list_file : str
        Text file containing list of files to swap.
    disc_dict_pair : list
        List containing a pair of dicts (one for source version,one for
        target version) that contain information about disc image, directory
        structure, and game files
    del_src_dir : bool
        Specifies whether to delete subdirectories containing the source
        files for the swaps. Default: False
    """

    # Read [SWAP] category of file lists for both source and
    # destination game versions.
    src_files_list = read_file_list(list_file, disc_dict_pair[1], file_category='[SWAP]')['[SWAP]']
    dst_files_list = read_file_list(list_file, disc_dict_pair[0], file_category='[SWAP]')['[SWAP]']
    files_to_swap = []
    total_files = 0

    # Loop through both source and target dictionaries simultaneously,
    # and append all mod-targeted src/dst pairs of files to a list of
    # files to swap.
    for (src_disc, dst_disc) in zip(sorted(src_files_list.keys(), key=numerical_sort),
                                    sorted(dst_files_list.keys(), key=numerical_sort)):
        for (src_key, dst_key) in zip(sorted(src_files_list[src_disc].keys(), key=numerical_sort),
                                      sorted(dst_files_list[dst_disc].keys(), key=numerical_sort)):
            # If a file is not flagged as a modding target, delete the file
            # from both dictionaries
            for f in src_files_list[src_disc][src_key][1:][::-1]:
                if f[1] == '0':
                    src_files_list[src_disc][src_key].remove(f)
                    dst_files_list[dst_disc][dst_key].remove(f)
                    if not src_files_list[src_disc][src_key][1:]:
                        del src_files_list[src_disc][src_key]
                        del dst_files_list[dst_disc][dst_key]
                    continue

            src_parent_dir = '_'.join((os.path.splitext(src_key)[0], 'dir'))
            src_basename = os.path.splitext(os.path.basename(src_key))[0]
            dst_parent_dir = '_'.join((os.path.splitext(dst_key)[0], 'dir'))
            dst_basename = os.path.splitext(os.path.basename(dst_key))[0]

            # Loop through all subfiles in the src/dst key, create the appropriate
            # subfile names,and append the src/dst pairs to a list of files to be
            # swapped. If the the subfile number given is '^' (current file) or
            # '*' (all files), the keys themselves are appended to the list.
            try:
                for file in src_files_list[src_disc][src_key][1:]:
                    if file[0] == '^' or file[0] == '*':
                        file_pair = (src_key, dst_key)
                    elif 'OV_' in src_key.upper() or 'SCUS' in src_key.upper() \
                            or 'SCES' in src_key.upper() or 'SCPS' in src_key.upper():
                        block_range = process_block_range(file[0], src_basename)
                        file_pair = ('.'.join((src_key, block_range)),
                                     '.'.join((dst_key, block_range)))
                    else:
                        file_pair = (os.path.join(
                            src_parent_dir, ''.join((src_basename, '_', file[0], '.bin'))),
                                     os.path.join(
                            dst_parent_dir, ''.join((dst_basename, '_', file[0], '.bin'))))
                    files_to_swap.append(file_pair)
                    total_files += 1
            except KeyError:
                pass

    files_swapped = 0
    print('\nLODModS: Swapping files')
    # Loop through src/dst pairs in files_to_swap and call file_swap() on it.
    i = 0
    for pair in files_to_swap:
        try:
            file_swap(pair[0], pair[1])
            if del_src_dir:
                parent_dir = os.path.split(pair[0])[0]
                os.remove(pair[0])
                try:
                    os.rmdir(parent_dir)
                except OSError:
                    pass
        except FileNotFoundError:
            print('LODModS: %s not found' % sys.exc_info()[1].filename)
            continue
        files_swapped += 1
        print('LODModS: Swapped %s of %s files' % (files_swapped, total_files), end='\r')

    print(ERASE + 'LODModS: Files swapped')
