"""Provides functionality to handle text.

This module contains functions to read and update pointer tables,
decode/encode text to/from TLoD's font table, dump text from game
files to CSV files, and insert text back into the game files from
CSV files.

Copyright (C) 2020 theflyingzamboni
"""

from copy import deepcopy
import csv
from more_itertools import sort_together
import mmap
import os
import re
import struct
import sys
from build_codec import *
from config_handler import read_file_list
from disc_handler import backup_file
from game_file_handler import process_block_range

is_insert = False

# Build custom standard and extended codecs for encoding/decoding LoD's
# text each time script is called. Allows for custom codecs that don't
# need to be located in the python codecs folder.
standard_table_end_val = build_codecs()
codecs.register(lod_codec.custom_search)
codecs.register(lod_ext_codec.getregentry)

VERSION_CODES = {'USA': 'SCUS', 'UK': 'SCESe', 'FRA': 'SCESf', 'GER': 'SCESg',
                 'ITA': 'SCESi', 'SPA': 'SCESs', 'JPN': 'SCPS'}
# TODO: Need text ends for other game versions, plus handles for multiple
#  SCES versions.
OV_TEXT_STARTS = {'SCUS': {'BTTL.OV_': [0x34b18],
                           'S_BTLD.OV_': [0x14460],
                           'S_ITEM.OV_': [0x18dfc, 0x1c698, 0x1e3b4, 0x1e998,
                                          0x200e4, 0x20a94],
                           'WMAP.OV_': [0x29088],
                           'SCUS_944.91': [0x40450, 0x40be8, 0x41858, 0x42168],
                           'SCUS_945.84': [0x40450, 0x40be8, 0x41858, 0x42168],
                           'SCUS_945.85': [0x40450, 0x40be8, 0x41858, 0x42168],
                           'SCUS_945.86': [0x40450, 0x40be8, 0x41858, 0x42168]},
                  'SCESe': {'BTTL.OV_': [],
                            'S_BTLD.OV_': [],
                            'S_ITEM.OV_': [],
                            'WMAP.OV_': [],
                            'SCES_030.43': [],
                            'SCES_130.43': [],
                            'SCES_230.43': [],
                            'SCES_330.43': []},
                  'SCESf': {'BTTL.OV_': [],
                            'S_BTLD.OV_': [],
                            'S_ITEM.OV_': [],
                            'WMAP.OV_': [],
                            'SCES_030.44': [],
                            'SCES_130.44': [],
                            'SCES_230.44': [],
                            'SCES_330.44': []},
                  'SCESg': {'BTTL.OV_': [],
                            'S_BTLD.OV_': [],
                            'S_ITEM.OV_': [],
                            'WMAP.OV_': [],
                            'SCES_030.45': [],
                            'SCES_130.45': [],
                            'SCES_230.45': [],
                            'SCES_330.45': []},
                  'SCESi': {'BTTL.OV_': [],
                            'S_BTLD.OV_': [],
                            'S_ITEM.OV_': [],
                            'WMAP.OV_': [],
                            'SCES_030.46': [],
                            'SCES_130.46': [],
                            'SCES_230.46': [],
                            'SCES_330.46': []},
                  'SCESs': {'BTTL.OV_': [],
                            'S_BTLD.OV_': [],
                            'S_ITEM.OV_': [],
                            'WMAP.OV_': [],
                            'SCES_030.47': [],
                            'SCES_130.47': [],
                            'SCES_230.47': [],
                            'SCES_330.47': []},
                  'SCPS1': {'BTTL.OV_': [],
                           'S_BTLD.OV_': [],
                           'S_ITEM.OV_': [],
                           'WMAP.OV_': [],
                           'SCPS_101.19': [],
                           'SCPS_101.20': [],
                           'SCPS_101.21': [],
                           'SCPS_101.22': []},
                  'SCPS4': {'BTTL.OV_': [],
                            'S_BTLD.OV_': [],
                            'S_ITEM.OV_': [],
                            'WMAP.OV_': [],
                            'SCPS_101.19': [],
                            'SCPS_101.20': [],
                            'SCPS_101.21': [],
                            'SCPS_101.22': []}}
OV_TEXT_ENDS = {'SCUS': {'BTTL.OV_': [0x34ce4],
                         'S_BTLD.OV_': [0x168f0],
                         'S_ITEM.OV_': [0x1c298, 0x1dfb4, 0x1e8ec, 0x1ffe4,
                                        0x20890, 0x21f9a],
                         'WMAP.OV_': [0x29b44],
                         'SCUS_944.91': [0x40ae8, 0x41758, 0x42018, 0x42734],
                         'SCUS_945.84': [0x40ae8, 0x41758, 0x42018, 0x42734],
                         'SCUS_945.85': [0x40ae8, 0x41758, 0x42018, 0x42734],
                         'SCUS_945.86': [0x40ae8, 0x41758, 0x42018, 0x42734]},
                'SCESe': {'BTTL.OV_': [],
                          'S_BTLD.OV_': [],
                          'S_ITEM.OV_': [],
                          'WMAP.OV_': [],
                          'SCES_030.43': [],
                          'SCES_130.43': [],
                          'SCES_230.43': [],
                          'SCES_330.43': []},
                'SCESf': {'BTTL.OV_': [],
                          'S_BTLD.OV_': [],
                          'S_ITEM.OV_': [],
                          'WMAP.OV_': [],
                          'SCES_030.44': [],
                          'SCES_130.44': [],
                          'SCES_230.44': [],
                          'SCES_330.44': []},
                'SCESg': {'BTTL.OV_': [],
                          'S_BTLD.OV_': [],
                          'S_ITEM.OV_': [],
                          'WMAP.OV_': [],
                          'SCES_030.45': [],
                          'SCES_130.45': [],
                          'SCES_230.45': [],
                          'SCES_330.45': []},
                'SCESi': {'BTTL.OV_': [],
                          'S_BTLD.OV_': [],
                          'S_ITEM.OV_': [],
                          'WMAP.OV_': [],
                          'SCES_030.46': [],
                          'SCES_130.46': [],
                          'SCES_230.46': [],
                          'SCES_330.46': []},
                'SCESs': {'BTTL.OV_': [],
                          'S_BTLD.OV_': [],
                          'S_ITEM.OV_': [],
                          'WMAP.OV_': [],
                          'SCES_030.47': [],
                          'SCES_130.47': [],
                          'SCES_230.47': [],
                          'SCES_330.47': []},
                'SCPS1': {'BTTL.OV_': [],
                         'S_BTLD.OV_': [],
                         'S_ITEM.OV_': [],
                         'WMAP.OV_': [],
                         'SCPS_101.19': [],
                         'SCPS_101.20': [],
                         'SCPS_101.21': [],
                         'SCPS_101.22': []},
                'SCPS4': {'BTTL.OV_': [],
                         'S_BTLD.OV_': [],
                         'S_ITEM.OV_': [],
                         'WMAP.OV_': [],
                         'SCPS_101.19': [],
                         'SCPS_101.20': [],
                         'SCPS_101.21': [],
                         'SCPS_101.22': []}}
END_FLAG = re.compile(b'\xff\xa0')
DUMP_FLAG_DICT = {b'\xa0\xff': '<END>', b'\xa1\xff': '<LINE>',
                  b'\xa3\xff': '<WWWTS>', b'\xa5\x00': '<START0>',
                  b'\xa5\x01': '<START1>', b'\xa5\x02': '<START2>',
                  b'\xa5\x03': '<START3>', b'\xa5\x04': '<START4>',
                  b'\xa5\x05': '<START5>', b'\xa5\x0a': '<STARTA>',
                  b'\xa5\x0f': '<STARTF>', b'\xa7\x00': '<TWHITE>',
                  b'\xa7\x01': '<TDGRN>', b'\xa7\x02': '<TLGRN>',
                  b'\xa7\x03': '<TCYAN>', b'\xa7\x04': '<TBRWN>',
                  b'\xa7\x05': '<TRED>', b'\xa7\x06': '<TMTAN>',
                  b'\xa7\x07': '<TLTAN>', b'\xa7\x08': '<TYLW>',
                  b'\xa7\x09': '<TBLCK>', b'\xa7\x0a': '<TGRAY>',
                  b'\xa7\x0b': '<TPRPL>', b'\xa8\x00': '<VAR0>',
                  b'\xa8\x01': '<VAR1>', b'\xa8\x02': '<VAR2>',
                  b'\xa8\x03': '<VAR3>', b'\xa8\x04': '<VAR4>',
                  b'\xa8\x08': '<VAR8>', b'\xa8\x09': '<VAR9>',
                  b'\xb0\x00': '<SAUTO0>', b'\xb0\x01': '<SAUTO1>',
                  b'\xb0\x02': '<SAUTO2>', b'\xb0\x03': '<SAUTO3>',
                  b'\xb0\x04': '<SAUTO4>', b'\xb0\x05': '<SAUTO5>',
                  b'\xb0\x09': '<SAUTO9>', b'\xb0\x0a': '<SAUTOA>',
                  b'\xb0\x1e': '<SAUTO1E>', b'\xb0\xff': '<SCUT>',
                  b'\xb1\x01': '<FIRE>', b'\xb1\x02': '<WATER>',
                  b'\xb1\x03': '<WIND>', b'\xb1\x04': '<EARTH>',
                  b'\xb1\x05': '<LIGHT>', b'\xb1\x06': '<DARK>',
                  b'\xb1\x07': '<THNDR>', b'\xb1\x08': '<NELEM>',
                  b'\xb1\x09': '<NORM>', b'\xb2\x00': '<SBAT>'}
INSERT_FLAG_DICT = {'<END>': b'\xff\xa0', '<LINE>': b'\xff\xa1',
                    '<WWWTS>': b'\xff\xa3', '<START0>': b'\x00\xa5',
                    '<START1>': b'\x01\xa5', '<START2>': b'\x02\xa5',
                    '<START3>': b'\x03\xa5', '<START4>': b'\x04\xa5',
                    '<START5>': b'\x05\xa5', '<STARTA>': b'\x0a\xa5',
                    '<STARTF>': b'\x0f\xa5', '<TWHITE>': b'\x00\xa7',
                    '<TDGRN>': b'\x01\xa7', '<TLGRN>': b'\x02\xa7',
                    '<TCYAN>': b'\x03\xa7', '<TBRWN>': b'\x04\xa7',
                    '<TRED>': b'\x05\xa7', '<TMTAN>': b'\x06\xa7',
                    '<TLTAN>': b'\x07\xa7', '<TYLW>': b'\x08\xa7',
                    '<TBLCK>': b'\x09\xa7', '<TGRAY': b'\x0a\xa7',
                    '<TPRPL>': b'\x0b\xa7', '<VAR0>': b'\x00\xa8',
                    '<VAR1>': b'\x01\xa8', '<VAR2>': b'\x02\xa8',
                    '<VAR3>': b'\x03\xa8', '<VAR4>': b'\x04\xa8',
                    '<VAR8>': b'\x08\xa8', '<VAR9>': b'\x09\xa8',
                    '<SAUTO0>': b'\x00\xb0', '<SAUTO1>': b'\x01\xb0',
                    '<SAUTO2>': b'\x02\xb0', '<SAUTO3>': b'\x03\xb0',
                    '<SAUTO4>': b'\x04\xb0', '<SAUTO5>': b'\x05\xb0',
                    '<SAUTO9>': b'\x09\xb0', '<SAUTOA>': b'\x0a\xb0',
                    '<SAUTO1E>': b'\x1e\xb0', '<SCUT>': b'\xff\xb0',
                    '<FIRE>': b'\x01\xb1', '<WATER>': b'\x02\xb1',
                    '<WIND>': b'\x03\xb1', '<EARTH>': b'\x04\xb1',
                    '<LIGHT>': b'\x05\xb1', '<DARK>': b'\x06\xb1',
                    '<THNDR>': b'\x07\xb1', '<NELEM>': b'\x08\xb1',
                    '<NORM>': b'\x09\xb1', '<SBAT>': b'\x00\xb2'}


class PointerTable:
    """
    A class for storing and managing text pointers and associated values.

    Objects of this class store lists of pointer values read from game files,
    as well as corresponding lists of pointer offsets, and the starting
    offsets of the pointer tables in the file for all pointer types. For
    absolute pointers like those in the OV_ files, the objects also store
    corresponding lists containing the high bytes of absolute pointers
    (the starting address to offset from), the differences in offsets between
    the pointer table in the game file and the table in RAM, and the starting
    offsets of the text blocks. The class also provides functions to handle
    appending and sorting of attribute values.

    Functions
    ---------
    append_attributes()
        Appends values to all attribute lists.
    sort_attributes()
        Sorts all attribute lists together by pointer value and offset.

    Attributes
    ----------
    ptrs : list
        List of pointer values.
    ptr_locs : list
        List of pointer offset locations in file.
    tbl_starts : list
        List of starting offsets of pointer tables.
    hi_bytes : list
        List of high bytes for absolute pointers (e.g. 0x80000000).
    offset_diffs : list
        List of differences between starts of tables in RAM and in file
        for absolute pointers.
    txt_starts : list
        List of starting offsets of text blocks corresponding to tables
        of absolute pointers.
    box_ptrs : list
        List of box pointer values.
    box_ptr_locs : list
        List of box pointer offset locations in file.
    box_tbl_starts : list
        List of starting offsets of pointer tables.
    """

    def __init__(self):
        self.ptrs = []
        self.ptr_locs = []
        self.tbl_starts = []
        self.hi_bytes = []
        self.offset_diffs = []
        self.txt_starts = []
        self.box_ptrs = []
        self.box_ptr_locs = []
        self.box_tbl_starts = []

    def __len__(self):
        return len(self.ptrs)

    def append_attributes(self, ptr=None, ptr_loc=None, tbl_start=None,
                          hi_byte=None, offset_diff=None, txt_start=None,
                          box_ptr=None, box_ptr_loc=None, box_tbl_start=None):
        """
        Appends values to all attribute lists.

        All of the passed arguments are appended to their corresponding
        attribute list. If no value is specified for a particular attribute,
        None is appended instead.

        Parameters
        ----------
        ptr : int
            Pointer value (default: None).
        ptr_loc : int
            Pointer offset location in file (default: None).
        tbl_start : int
            Starting offset of current pointer table (default: None).
        hi_byte : int
            High byte for absolute pointer (default: None).
        offset_diff : int
            Differences between start of current table in RAM and in file
            for absolute pointer (default: None).
        txt_start : int
            Starting offset of text block corresponding to current pointer
            table of absolute pointers (default: None).
        box_ptr : int
            Box pointer value (default: None).
        box_ptr_loc : int
            Box pointer offset location in file (default: None).
        box_tbl_start : int
            Starting offset of current box pointer table (default: None)
        """

        self.ptrs.append(ptr)
        self.ptr_locs.append(ptr_loc)
        self.tbl_starts.append(tbl_start)
        self.hi_bytes.append(hi_byte)
        self.offset_diffs.append(offset_diff)
        self.txt_starts.append(txt_start)
        self.box_ptrs.append(box_ptr)
        self.box_ptr_locs.append(box_ptr_loc)
        self.box_tbl_starts.append(box_tbl_start)

    def sort_attributes(self):
        """
        Sorts all attribute lists together.

        Sort keys are pointer value first, with pointer location as the
        secondary key.
        """
        self.ptrs, self.ptr_locs, self.tbl_starts, self.hi_bytes,\
            self.offset_diffs, self.txt_starts, self.box_ptrs,\
            self.box_ptr_locs, self.box_tbl_starts = \
            sort_together(
                [self.ptrs, self.ptr_locs, self.tbl_starts, self.hi_bytes,
                 self.offset_diffs, self.txt_starts, self.box_ptrs,
                 self.box_ptr_locs, self.box_tbl_starts], key_list=(0, 1))

        self.ptrs, self.ptr_locs, self.tbl_starts, self.hi_bytes,\
            self.offset_diffs, self.txt_starts, self.box_ptrs,\
            self.box_ptr_locs, self.box_tbl_starts = \
            list(self.ptrs), list(self.ptr_locs),\
            list(self.tbl_starts), list(self.hi_bytes),\
            list(self.offset_diffs), list(self.txt_starts),\
            list(self.box_ptrs), list(self.box_ptr_locs),\
            list(self.box_tbl_starts)

    def calculate_pointer(self, file, index, ptr_type='txt'):
        """
        Write updated pointer to file and return it.

        Uses current file offset to calculate updated pointer depending on
        pointer type, then writes the new value to the file and returns that
        value.

        Parameters
        ----------
        file : BufferedReader
            Game file containing text.
        index : int
            Index of current pointer in PointerTable object.
        ptr_type : str
            Indicates whether pointer is a text or box pointer.

        Returns
        -------
        byte string
            Little-endian 4-byte pointer.
        """

        if ptr_type == 'txt':
            tbl_start = self.tbl_starts[index]
        elif ptr_type == 'box':
            tbl_start = self.box_tbl_starts[index]
        else:
            print('Invalid pointer type')
            raise ValueError

        if self.hi_bytes[index] is None:
            new_ptr = (file.tell() - tbl_start) >> 2
        elif self.hi_bytes[index] & 0x09000000 == 0x09000000:
            if ptr_type == 'box':
                if self.tbl_starts[index] - self.box_tbl_starts[index] == 36:
                    offset_adjustment = (self.hi_bytes[index] ^ 0x09000000) - 20
                else:
                    offset_adjustment = (self.hi_bytes[index] ^ 0x09000000) - 8
            else:
                offset_adjustment = self.hi_bytes[index] ^ 0x09000000
            new_ptr = ((file.tell() - tbl_start + offset_adjustment)
                       >> 2) | 0x09000000 if ptr_type == 'txt' \
                else ((file.tell() - tbl_start + offset_adjustment)
                      >> 2)
        elif self.hi_bytes[index] == 0x80000000:
            new_ptr = (file.tell() + self.offset_diffs[index]) \
                      | self.hi_bytes[index]
        else:
            new_ptr = ((file.tell() + self.offset_diffs[index] ^ 0x110000) & 0xffff)\
                      | self.hi_bytes[index]

        if new_ptr > 0x80000000:
            new_ptr = new_ptr.to_bytes(4, 'little')
        else:
            new_ptr = struct.pack('<i', new_ptr)

        return new_ptr


def _get_rel_pointers(file, ptr_tbl_starts, ptr_tbl_ends, single_ptr_tbl):
    """
    Reads tables of relative pointers.

    Reads pointers used for text in field areas (contained within MRG files
    in DRGN0, DRGN1, and DRGN2x) into PointerTable object, then returns it.
    These pointers are calculated as the relative offset from the start of a
    particular pointer table. The pointer values themselves are shifted left
    two bits (to word-align values) before being added to the table starting
    offset.

    This function allows for the input of multiple pointer tables (as some
    files have more than one located in different parts of the file), as well
    as dual pointer tables (where the text pointer table is immediately
    followed by a pointer table for the text box dimensions). In the latter
    case, the ends of the pointer tables are specified as the offset following
    both the text and box pointer tables.

    The pointer table is sorted prior to return according to value, so that all
    text will be dumped/inserted in the order it occurs, regardless of the
    position of the pointer itself (as these may be out of order relative to
    the text).

    Parameters
    ----------
    file : BufferedReader
        Game file containing text.
    ptr_tbl_starts : int list
        List of starting offsets of all pointer tables in file.
    ptr_tbl_ends : int list
        List of ending offsets of all pointer tables in file.
    single_ptr_tbl : int list
        List of 0/1 values indicating whether each pointer table is single
        (text only) or double (box pointers too).

    Returns
    -------
    PointerTable
        Returns PointerTable object for text and box pointers
    """

    ptr_tbl = PointerTable()

    # Loop through each pointer table in the file.
    for index, start in enumerate(ptr_tbl_starts):
        # If it's a dual table, length is half the difference of end - start.
        # Start of box table will be the end of the text table.
        tbl_length = (ptr_tbl_ends[index] - start
                      if single_ptr_tbl[index]
                      else (ptr_tbl_ends[index] - start) // 2)
        box_tbl_start = start + tbl_length if not single_ptr_tbl[index] else None

        # Loop through current table 4 bytes at a time, calculate the absolute
        # pointer value, then add that, the offset of the pointer, and the start
        # of the pointer table to the attributes in the text pointer table
        # object. If there is a box pointer table as well, do the same for it.
        curr_rel_offset = 0x00
        while curr_rel_offset < tbl_length:
            file.seek(start + curr_rel_offset)
            offset_adjustment = 0x00
            box_ptr_offset_adjustment = 0x00
            raw_ptr = file.read(4)
            if raw_ptr[3] == 0x09:
                test_bytes = file.read(8)
                if test_bytes == b'\x49\x00\x00\x00\x38\x01\xc0\x00' \
                        or test_bytes == b'\x40\x01\x00\x00\x0d\x00\x00\x09':
                    offset_adjustment += 0x28
                else:
                    file.seek(file.tell()-0x28)
                    test_bytes = file.read(12)
                    if test_bytes ==\
                            b'\x38\x06\xc6\x00\x00\x00\x00\x00\x40\x00\x00\x0f':
                        offset_adjustment += 0x1c
                        box_ptr_offset_adjustment = 0x24
                        box_tbl_start = start - box_ptr_offset_adjustment
                    elif test_bytes ==\
                            b'\x03\x00\x00\x00\x00\x00\x00\x01\x11\x01\x00\x00':
                        offset_adjustment += 0x20
                        # Correction hacks for the condition where there are box pointers
                        box_ptr_offset_adjustment = 8
                        box_tbl_start = start - box_ptr_offset_adjustment
                    else:
                        print(f'Invalid pointer at {start+curr_rel_offset}.')
                        raise ValueError
                extra_bytes = 0x09000000 | offset_adjustment
                ptr = int.from_bytes(raw_ptr[:3], 'little')
            else:
                extra_bytes = None
                ptr = struct.unpack('<i', raw_ptr)[0]
            ptr = (ptr << 2) + start - offset_adjustment

            if not single_ptr_tbl[index]:
                file.seek(box_tbl_start + curr_rel_offset)
                box_ptr = struct.unpack('<i', file.read(4))[0]
                box_ptr = (box_ptr << 2) + box_tbl_start
                ptr_tbl.append_attributes(
                    ptr, start + curr_rel_offset, start, extra_bytes,
                    box_ptr=box_ptr, box_ptr_loc=box_tbl_start + curr_rel_offset,
                    box_tbl_start=box_tbl_start)
            elif single_ptr_tbl[index] in (3, 4):
                file.seek(start - box_ptr_offset_adjustment)
                if single_ptr_tbl[index] == 3:
                    box_ptr = struct.unpack('<i', file.read(4))[0] ^ 0x09000000
                    box_ptr = (box_ptr << 2) + box_tbl_start - 8
                else:
                    box_ptr = struct.unpack('<i', file.read(4))[0] ^ 0x13000000
                    box_ptr = (box_ptr << 2) + box_tbl_start - (offset_adjustment - 8)
                ptr_tbl.append_attributes(
                    ptr, start + curr_rel_offset, start, extra_bytes,
                    box_ptr=box_ptr, box_ptr_loc=box_tbl_start,
                    box_tbl_start=box_tbl_start)
            else:
                ptr_tbl.append_attributes(
                    ptr, start + curr_rel_offset, start, extra_bytes)

            curr_rel_offset += 0x04

    ptr_tbl.sort_attributes()

    return ptr_tbl


def _get_abs_pointers(file, ptr_tbl_starts, ptr_tbl_ends, text_starts):
    """
    Reads tables of absolute pointers.

    Reads pointers used for text in battle, menus, and the world map (contained
    within OV_ files) into PointerTable object, then returns it. These
    values are or are calculated from absolute positions in RAM, and come in
    two varieties: absolute (high byte is 0x80) and instructional (pointer is
    an addiu instruction that adds the two low bytes to 0x110000). The latter
    is only encountered in S_ITEM.OV_.

    This function allows for the input of multiple pointer tables (as some
    files have more than one located in different parts of the file).

    The pointer tables is sorted prior to return according to value, so that all
    text will be dumped/inserted in the order it occurs, regardless of the
    position of the pointer itself (as these may be out of order relative to
    the text).

    Parameters
    ----------
    file : BufferedReader
        Game file containing text.
    ptr_tbl_starts : int list
        List of starting offsets of all pointer tables in file.
    ptr_tbl_ends : int list
        List of ending offsets of all pointer tables in file.
    text_starts : int list
        List of starting offsets of text blocks corresponding to pointer
        tables.

    Returns
    -------
    PointerTable
        Returns PointerTable object for text and box pointers
    """

    ptr_tbl = PointerTable()

    # Loop through each pointer table in the file.
    for index, start in enumerate(ptr_tbl_starts):
        tbl_length = ptr_tbl_ends[index] - start

        # Read the first pointer of the pointer table. This needs to be done
        # once before looping so that the offset difference between the first
        # pointer (a RAM location) and the text start in the game file can be
        # calculated. This difference will be used to recalculate the pointers
        # in terms of the game file, and convert them back later.
        file.seek(start)
        ptr = file.read(4)
        if ptr[3:] == b'\x80':  # Absolute pointers
            extra_bytes = 0x80000000
            ptr = int.from_bytes(ptr[:3], 'little')
        elif ptr[3:] == b'\x24' or ptr[3:] == b'\x26':  # Instructional pointers
            # Only occurs as single-value 'table'.
            extra_bytes = int.from_bytes(ptr[2:], 'little') << 16
            ptr = int.from_bytes(ptr[:2], 'little') + 0x110000
        else:  # This shouldn't happen, but need to double-check
            print('Make sure pointer offsets are correct.')
            sys.exit(-6)

        curr_rel_offset = 0x00
        offset_diff = ptr - text_starts[index]
        ptr_tbl.append_attributes(
            text_starts[index], start + curr_rel_offset, start,
            extra_bytes, offset_diff, text_starts[index])

        # Loop through current table 4 bytes at a time, reads the absolute
        # RAM pointer value, then use offset difference to convert to game
        # file pointer. Then, add the pointer, the offset of the pointer,
        # the start of the pointer table, the high byte value, the offset
        # difference, and the starting offset of the text block to the
        # attributes in the text pointer table object.
        curr_rel_offset += 0x04
        extra_bytes = 0x80000000
        while curr_rel_offset < tbl_length:
            ptr = file.read(4)
            if ptr[3:] == b'\x80' and ptr[2:3] != b'\x00':
                ptr = int.from_bytes(ptr[:3], 'little')
            else:  # WMAP has non-pointer values in table to skip.
                curr_rel_offset += 0x04
                continue

            ptr -= offset_diff
            if ptr >= text_starts[index]:
                # Can't remember if or why this check is necessary,
                # just leave it.
                ptr_tbl.append_attributes(
                    ptr, start + curr_rel_offset, start,
                    extra_bytes, offset_diff, text_starts[index])
            curr_rel_offset += 0x04

    ptr_tbl.sort_attributes()
    return ptr_tbl


def _decode_text_block(input_file, text_start=None):
    """
    Decode game text into Unicode and return decoded text.

    Reads byte-pairs from current position in file and decodes them into
    Unicode characters until the end-text token is encountered, then reads
    the box dimension bytes if present. Two copies of the decoded text block
    and one of the box dimensions are returned so that they can be written
    to a CSV. Decodes everything beyond the end hex of the standard table as
    italics and surrounds text with {} to denote this.

    Parameters
    ----------
    input_file : BufferedReader
        Game file containing text.
    text_start : int
        Start of the current text block in an OV_ (default: None)

    Returns
    -------
    (str, str, str)
        Tuple containing two copies of the decoded text string and one string
        containing the box dimensions.
    """

    byte_pair = None
    italics = False
    char_list = []
    box_dims = []

    # Loop through two-byte characters in text until end flag encountered.
    while byte_pair != b'\xa0\xff':
        # Characters where high byte is 0x00 need to be repacked as single
        # byte to decode properly.
        byte_pair = input_file.read(2)
        half_word_val = struct.unpack('<H', byte_pair)[0]
        if half_word_val <= 0xff:
            byte_pair = struct.pack('B', half_word_val)
        else:
            byte_pair = struct.pack('>H', half_word_val)

        # If the 2-byte sequence isn't a flag, decode and write the character.
        # Otherwise, write the text flag.
        if byte_pair not in DUMP_FLAG_DICT.keys():
            # Decode bytes using extended table (for italics) if the value
            # is greater than the end of the standard table, otherwise decode
            # using the standard table. Write { and } to csv to delineate
            # italics.
            try:
                if half_word_val > standard_table_end_val \
                        and not italics:
                    char_list.append('{')
                    italics = True
                elif 0x00 < half_word_val <= standard_table_end_val \
                        and italics:
                    char_list.append('}')
                    italics = False

                if italics is True:
                    char = byte_pair.decode('lod_extended', errors='strict')
                else:
                    char = byte_pair.decode('lod', errors='strict')
            except UnicodeDecodeError as e:
                print('Dump: Encountered unknown character %s at offset %s '
                      'while dumping file %s' %
                      (byte_pair, hex(input_file.tell() - 2), input_file.name))
                raise e
            else:
                char_list.append(char)
        else:
            if italics is True:  # Close italics if they haven't been already.
                char_list.append('}')
                italics = False

            char_list.append(DUMP_FLAG_DICT[byte_pair])
            if byte_pair == b'\xa1\xff':
                char_list.append('\n')
    else:  # After loop exits successfully
        # Maintain word alignment on text segment starts.
        if input_file.tell() % 4 == 2:
            input_file.seek(input_file.tell() + 2)

        # Read the bytes for the box dimensions and write them to the csv.
        if text_start is None:  # Proxy for non-OV_ file
            box_size = input_file.read(8)
        else:
            # OV_'s mainly have 4-byte box dimensions rather than 8-byte.
            # Some menu text does not have box dimensions and should be
            # an empty string.
            box_size = input_file.read(4)
            if box_size[2:3] not in (b'\x01', b'\x02', b'\x03'):
                box_size = b''
                input_file.seek(input_file.tell() - 4)

        for char in box_size:
            if char:
                box_dims.append('%s' % hex(char)[2:].zfill(2))
            else:
                box_dims.append(' ')

    text_block = ''.join(char_list)
    return text_block, text_block, ''.join(box_dims)


def _encode_text_block(text_block, text_offset):
    """
    Encode text to LoD's font table and return list of byte pairs to write.

    Reads characters in a text block and encodes them into LoD's encoding,
    converting tokens into their respective byte-pairs as well. Each pair
    is then appended to a list to be written to the game file. If the length
    of the list times 2 is not divisible by 4, an additional 0x00 pair is
    appended to the end. The list is then returned. Encodes everything
    designated as italics with the wrapper {} as belonging to the extended
    table.

    Parameters
    ----------
    text_block : str
        Block of text read from a CSV entry.
    text_offset : int
        File offset at which text block starts.

    Returns
    -------
    list
        A list containing byte-pairs to write to game file.
    """

    i = 0
    italics = False
    char_list_to_write = []
    while i < len(text_block):
        if text_block[i] == '{':
            italics = True
            i += 1
            continue
        elif text_block[i] == '}':
            italics = False
            i += 1
            continue

        if text_block[i] == '<':
            flag_end_index = text_block[i:].find('>')
            flag = text_block[i:i + flag_end_index + 1]
            if italics and (flag == '<LINE>' or flag == 'END'):
                italics = False
            byte_pair = INSERT_FLAG_DICT[flag]
            char_list_to_write.append(byte_pair)
            i = i + flag_end_index + 1
        else:
            try:
                if italics:
                    char = text_block[i].encode('lod_extended')
                else:
                    char = text_block[i].encode('lod')
            except UnicodeEncodeError as e:
                print('Insert: Encountered unknown character "%s" in "%s" '
                      'while inserting file' %
                      (text_block[i], text_block[:i + 1]))
                raise e

            if int.from_bytes(char, 'big') <= 0xff:
                byte_pair = struct.pack('<H', *struct.unpack('B', char))
            else:
                byte_pair = struct.pack('<H', *struct.unpack('>H', char))
            char_list_to_write.append(byte_pair)
            i += 1
    else:
        if (text_offset + (len(char_list_to_write)) * 2) % 4 == 2:
            char_list_to_write.append(b'\x00\x00')

        return char_list_to_write


def update_box_dimensions(csv_file):
    """
    Updates the box dimensions column in a CSV to fit new text dimensions.

    Loops through a CSV file and calculates the maximum character width
    and line count for each text entry (after stripping out flags),
    then writes these values as box dimensions in the box dimensions
    column so that manual updating unnecessary.

    Parameters
    ----------
    csv_file : str
        Full path and file name to CSV being updated.
    """

    updated_rows = []
    with open(csv_file, 'r', encoding='utf-16', newline='') as f:
        csvreader = csv.reader(f, delimiter='\t')
        updated_rows.append(next(csvreader))
        for row in csvreader:
            # Make sure there are box dimensions to update first.
            try:
                row[4]
            except IndexError:
                continue
                
            new_text = row[3]
            new_text = re.sub('[{}]', '', new_text)
            new_text_list = new_text.split('\n')
            num_lines = f'{len(new_text_list):02x}'
            max_line_len = 0
            for line in new_text_list:
                extra_var_len = 8 * len(re.findall('<VAR.>', line))
                line_len = len(re.sub('<.*?>', '', line))
                if line_len == 0:
                    line_len = 1
                else:
                    line_len += extra_var_len
                if line_len > max_line_len:
                    max_line_len = line_len
            else:
                max_line_len = f'{max_line_len:02x}'

            old_box_dims = row[4]
            box_dims = re.sub('^[a-f0-9]{2}', max_line_len, old_box_dims)
            box_dims = re.sub('(?<= )[a-f0-9]{2}', num_lines, box_dims)
            row[4] = box_dims
            updated_rows.append(row)

    with open(csv_file, 'w', encoding='utf-16', newline='') as f:
        csvwriter = csv.writer(f, delimiter='\t')
        csvwriter.writerows(updated_rows)


def dump_text(file, csv_file, ptr_tbl_starts, ptr_tbl_ends,
              single_ptr_tbl, ov_text_starts=None, called=False):
    """
    Dumps text from a game file.

    Reads pointers in all specified pointer tables (some files have multiple,
    particularly OV_'s) into a single ordered list, then goes through each
    one in order, reads the text until encountering the end flag, and decodes
    each character according to the LoD font table the user has specified in
    their .tbl file. All decoded text is added to a list along with the file
    name, text entry number, and box dimensions, which are appended to a CSV
    file. The CSV file will be initialized either by the command prompt
    interface or the dump_all() function so that functionality in this function
    is consistent regardless of whether it is used singly or as part of a batch
    process.

    Parameters
    ----------
    file : str
        Full path name of the file from which to dump text.
    csv_file : str
        CSV file to which to output text.
    ptr_tbl_starts : int list
        List of starting offsets of pointer tables in file.
    ptr_tbl_ends : int list
        List of ending offsets of pointer tables in file.
    single_ptr_tbl : bool list
        Indicates whether pointer tables are dual (text and box tables)
        (default: (False, )).
    ov_text_starts : int list
        List of starting offsets of text blocks in OV_ files (default: None).
    called : bool
        Indicates whether function was called from _dump_helper()
        (default: False).
    """

    global is_insert
    is_insert = False
    file_size = os.path.getsize(file)
    basename = os.path.splitext(os.path.basename(file))[0]
    csv_output = []

    with open(file, 'rb') as inf:
        # Check for addition text, pop relevant entries from parameter lists,
        # and dump additions.
        for index, val in enumerate(single_ptr_tbl):
            if val == 2:
                add_tbl_start = ptr_tbl_starts.pop(index)
                add_tbl_end = ptr_tbl_ends.pop(index)
                single_ptr_tbl.pop(index)
                ov_text_starts.pop(index)
                add_basename = '_'.join((basename, 'additions'))
                inf.seek(add_tbl_start)
                addition_block_size = add_tbl_end - add_tbl_start
                additions_block = inf.read(addition_block_size)

                # Split additions by character, then decode and append each
                # character's additions as a new CSV row.
                additions_list = [x for x in additions_block.split(b'\x00\x00') if x]
                for i, bytestr in enumerate(additions_list, start=1):
                    char_list = []
                    for byte in bytestr:
                        if byte == 0x00:
                            char_list.append('\n')
                        else:
                            char_list.append(byte.to_bytes(1, 'little').decode('ascii'))

                    add_string = ''.join(char_list)
                    csv_row = [add_basename, i, add_string, add_string]
                    csv_output.append(csv_row)
                break

        if ptr_tbl_starts:  # Need to check that addition wasn't only thing being dumped
            # Get text pointer list.
            if ov_text_starts is None:
                ptr_list = _get_rel_pointers(
                    inf, ptr_tbl_starts, ptr_tbl_ends, single_ptr_tbl)
            else:
                ptr_list = _get_abs_pointers(
                    inf, ptr_tbl_starts, ptr_tbl_ends, ov_text_starts)

            # Decode text block for each unique pointer.
            entry_num = 1
            for index, ptr in enumerate(ptr_list.ptrs):
                # Skip pointer if it is a duplicate.
                if index > 0 and ptr == ptr_list.ptrs[index-1]:
                    continue

                try:
                    # Make sure pointer value is valid and doesn't exceed file size.
                    if ptr < file_size:
                        inf.seek(ptr)
                    else:
                        raise EOFError

                    # Decode text block and create list for entry as csv row.
                    csv_row = [basename, entry_num,
                               *_decode_text_block(inf, ov_text_starts)]
                    csv_output.append(csv_row)
                    entry_num += 1
                except EOFError as e:
                    print('Dump: Pointer value at offset %s exceeds size of %s'
                          '\nDump: Skipping file' %
                          (hex(ptr_list.ptr_locs[index]), file))
                    if called:
                        raise e
                    else:
                        sys.exit(5)
                except UnicodeDecodeError as u:
                    print('Dump: Skipping file')
                    if called:
                        raise u
                    else:
                        sys.exit(3)

    # Write all text entries to a CSV.
    try:
        with open(csv_file, 'a', encoding='utf-16', newline='') as outf:
            csvwriter = csv.writer(outf, delimiter='\t')
            for row in csv_output:
                csvwriter.writerow(row)
    except PermissionError:
        print('Dump: Could not access %s. Make sure file is closed' % csv_file)


def dump_all(list_file, disc_dict):
    """
    Dumps text from all files listed in a file list text file.

    Reads file from file list text file and adds all files with additional
    text dumping parameters to a list of files to dump text from. A new blank
    CSV is created for each disc that contains files to dump. The function
    then loops through these and calls dump_text() on each one, dumping text
    to their respective CSVs.

    This function should be used with output txt file from id_file_type.
    This has already been done for each disc.

    Parameters
    ----------
    list_file : str
        Text file containing list of source files to dump text from.
    disc_dict : dict
        Dict containing information about disc image, directory structure,
        and game files
    """
    print('\nDump: Dumping script files')

    # For each disc in the file list, create an entry in script_dict with
    # the name of the corresponding CSV to dump text for that disc to.
    files_list = read_file_list(list_file, disc_dict, file_category='[PATCH]')['[PATCH]']
    if len(files_list) == 0:
        print('\nDump: No files found in file list.')
        sys.exit(7)

    script_dict = {}
    for key in list(files_list.keys()):
        file_parts = [x for x in os.path.split(disc_dict[key][2])]
        file_parts[1] = '.'.join((file_parts[1].replace(' ', '_'), 'csv'))
        script_dict[key] = os.path.join(*file_parts)

    # Loop through each disc in the file list and add all files with text dump
    # parameters to list of files to dump text from.
    scripts_dumped = 0
    total_scripts = 0
    files_to_dump = []
    for disc, disc_val in files_list.items():
        csv_file = script_dict[disc]

        # Loop through all files listed for each disc.
        for key, val in disc_val.items():
            parent_dir = '_'.join((os.path.splitext(key)[0], 'dir'))
            base_name = os.path.splitext(os.path.basename(key))[0]

            # Loop through all subfiles listed for each file.
            for file in val[1:]:
                # Convert file number to full file name with path.
                file_num = file[0]
                if 'OV_' in key.upper() or 'SCUS' in key.upper() \
                        or 'SCES' in key.upper() or 'SCPS' in key.upper():
                    block_range = process_block_range(file_num, base_name)
                    extension = os.path.splitext(key)[1]
                    file[0] = os.path.join(
                        parent_dir, ''.join((base_name, '_', block_range, extension)))
                else:
                    file[0] = os.path.join(
                        parent_dir, ''.join((base_name, '_', file_num, '.BIN')))

                # Convert all parameters to their appropriate data types,
                # append the appropriate csv_file to the end of the list
                # container with the file parameters, and append file to
                # list of files to dump. Items with too few parameters
                # will not be added.
                try:
                    file[1] = int(file[1])
                    file[2] = [int(x, 16) for x in file[2].split(',')]
                    file[3] = [int(x, 16) for x in file[3].split(',')]
                    file[4] = [int(x) for x in file[4].split(',')]
                    if file[5] == '0' or file[5].lower() == 'none':
                        file[5] = None
                    else:
                        file[5] = [int(x, 16) for x in file[5].split(',')]
                    file.append(csv_file)
                    files_to_dump.append(file)
                except IndexError:
                    if val[1][1]:
                        print('Dump: Fewer than 6 parameters given in %s, file %s\n'
                              'Dump: Skipping file' % (key, file_num))
                    continue
                except ValueError:
                    print('Dump: Invalid value in "%s"\n'
                          'Dump: Skipping file' % file)
                    continue
                else:
                    scripts_dumped += 1
                finally:
                    if val[1][1]:
                        total_scripts += 1

    # For each disc in script_dict, create a corresponding CSV with a header
    # row.
    for disc in script_dict.keys():
        try:
            os.makedirs(file_parts[0], exist_ok=True)
            with open(script_dict[disc], 'w', encoding='utf-16', newline='') as outf:
                csvwriter = csv.writer(outf, delimiter='\t')
                csvwriter.writerow(['File Name', 'Entry #', 'Original Dialogue',
                                    'New Dialogue', 'Box Dimensions'])
        except PermissionError:
            print('Dump: Could not access %s. Make sure file is closed' %
                  script_dict[disc])

    # Dump text from each file listed in files_to_dump.
    for file in sorted(files_to_dump):
        try:
            dump_text(file[0], file[6], file[2], file[3], file[4], file[5], True)
        except FileNotFoundError:
            print('Dump: File %s not found\nDump: Skipping file' %
                  sys.exc_info()[1].filename)
            scripts_dumped -= 1
        except EOFError:
            scripts_dumped -= 1
        except UnicodeDecodeError:
            scripts_dumped -= 1

    print('Dump: Dumped %s of %s script files\n' %
          (scripts_dumped, total_scripts))


def insert_text(file, csv_file, ptr_tbl_starts, ptr_tbl_ends,
                single_ptr_tbl, ov_text_starts=None,
                version='USA', called=False):
    """
    Inserts text into a game file.

    First checks whether text to insert includes additions. If so, these are
    popped from the parameters lists, and the addition text is inserted prior
    to inserting normal text.

    Reads pointers in all specified pointer tables (some files have multiple,
    particularly OV_'s) into a single ordered list, and reads all corresponding
    text entries from a CSV in entry order. The function then goes through all
    pointers/text entries, encodes each character according to the LoD font
    table the user has specified in their .tbl file, updates the pointer value,
    and writes the encoded text to the file along with box dimensions. Duplicate
    pointers are updated to match the value of the first occurring pointer, and
    pointers for duplicate text are updated to point to the first occurrence of
    that text to save space. At the end, the updated pointers are written to the
    game file.

    Parameters
    ----------
    file : str
        Full path name of the file into which to insert text.
    csv_file : str
        CSV file from which to read text for insertion.
    ptr_tbl_starts : int list
        List of starting offsets of pointer tables in file.
    ptr_tbl_ends : int list
        List of ending offsets of pointer tables in file.
    single_ptr_tbl : bool list
        Indicates whether pointer tables are dual (text and box tables).
    ov_text_starts : int list
        List of starting offsets of text blocks in OV_ files (default: None).
    version : str
        Game version being modded. Needed for OV text block offsets.
    called : bool
        Indicates whether function was called from _dump_helper()
        (default: False).
    """

    # Set additional variables
    global is_insert
    is_insert = True
    version = VERSION_CODES[version]
    if 'OV_' in file.upper() or 'SCUS' in file.upper() \
            or 'SCES' in file.upper() or 'SCPS' in file.upper():
        file_key = re.sub('_{.*}', '', os.path.basename(file.upper()))
        combat_ptrs = False
    else:
        file_key = os.path.basename(file.upper())
        combat_ptrs = True if 'DRGN0' in file_key.upper() \
                              or 'DRGN1' in file_key.upper() else False

    backup_file(file, True, True)  # Always insert to clean file.

    # Read all CSV entries for file being modified into a list.
    text_list = []
    additions_list = []
    basename = os.path.splitext(os.path.basename(file))[0]
    with open(csv_file, 'r', encoding='utf-16', newline='') as inf:
        csvreader = csv.reader(inf, delimiter='\t')
        for row in csvreader:
            if basename.upper() == row[0].upper():
                row[3] = row[3].replace('\n', '')
                row[3] = row[3].replace('\u2018', '\u0027').replace('\u2019', '\u0027')
                row[3] = row[3].replace('\u201c', '\u0022').replace('\u201d', '\u0022')
                row[4] = row[4].replace(' ', '00')
                text_list.append([int(row[1]), row[3], row[4]])
            elif 'additions' in row[0]:
                row[3] = row[3].replace('\u2018', '\u0027').replace('\u2019', '\u0027')
                row[3] = row[3].replace('\u201c', '\u0022').replace('\u201d', '\u0022')
                additions_list.append([int(row[1]), row[3]])
        additions_list.sort()
        additions_block = '\n\n'.join([x[1] for x in additions_list])
        text_list.sort(reverse=True)

    file_size = os.path.getsize(file)
    with open(file, 'rb+') as outf:
        data = mmap.mmap(outf.fileno(), 0)

        # Pop addition block parameters from pointer parameters and
        # write additions, if present in file.
        for index, val in enumerate(single_ptr_tbl[::]):
            if val == 2:
                add_tbl_start = ptr_tbl_starts.pop(index)
                add_tbl_end = ptr_tbl_ends.pop(index)
                single_ptr_tbl.pop(index)
                ov_text_starts.pop(index)

                # Make sure not to overflow addition block
                addition_block_size = add_tbl_end - add_tbl_start
                if len(additions_block) > addition_block_size:
                    print(f'Insert: Length of text exceeds size of addition block ' 
                          f'by {len(additions_block)-addition_block_size} bytes.')
                    return

                outf.seek(add_tbl_start)
                for char in additions_block:
                    if char == '\n':
                        outf.write(b'\x00')
                    else:
                        outf.write(char.encode('ascii'))
                outf.write((addition_block_size - len(additions_block)) * b' ')

                break

        # Now handle normal pointers.
        # Get text pointer list, and box pointer list if present.
        if ov_text_starts is None:
            ptr_list = _get_rel_pointers(outf, ptr_tbl_starts,
                                         ptr_tbl_ends, single_ptr_tbl)
        else:
            ptr_list = _get_abs_pointers(outf, ptr_tbl_starts, ptr_tbl_ends,
                                         ov_text_starts)
            curr_text_block = 0

        # Get box pointer list if needed for combat file pointer text
        # length limits.
        if combat_ptrs:
            for index, ptr in enumerate(ptr_list.ptrs):
                txt_end = END_FLAG.search(data, ptr).end()
                if txt_end % 4 == 0:
                    box_offset = txt_end
                else:
                    box_offset = txt_end + 2
                ptr_list.box_ptrs[index] = box_offset

        outf.seek(0)

        # Check for extra code following text.
        extra_code_start = None
        extra_code_end = None
        if ptr_list.txt_starts[index] is None:
            final_end_flag_loc = data.rfind(b'\xff\xa0')
            text_end = final_end_flag_loc + 10 if final_end_flag_loc % 4 \
                else final_end_flag_loc + 12
            if text_end < file_size:
                extra_code_start = text_end
                extra_code_end = file_size

        # Jump to first pointer address.
        curr_txt_offset = ptr_list.ptrs[0]
        outf.seek(curr_txt_offset)

        # Insert text for each unique pointer.
        dupe_check_text = []
        prev_txt_ptr = 0
        remaining_ptrs = sorted(deepcopy(ptr_list.ptrs), reverse=True)
        for index, ptr in enumerate(ptr_list.ptrs):
            remaining_ptrs.pop()
            # Update duplicate pointers.
            if ptr == prev_txt_ptr:
                # Check necessary for "Goods" line (0x1026) and "Yes" line
                # (0x6424), because the dupe pointer uses different registers.
                if ptr_list.hi_bytes[index] is not None \
                        and 0x09000000 < ptr_list.hi_bytes[index] < 0x80000000:
                    hi_bytes = ptr_list.hi_bytes[index] >> 16
                    hi_bytes = hi_bytes.to_bytes(2, 'little')
                    new_txt_ptr = b''.join((new_txt_ptr[:2], hi_bytes))

                ptr_list.ptrs[index] = new_txt_ptr
                if ptr_list.box_ptr_locs[index] is not None:
                    ptr_list.box_ptrs[index] = new_box_ptr
                continue

            text_block = text_list.pop()

            # Update current text pointer.
            for i, entry in enumerate(dupe_check_text):
                # Check if text is duplicate, and set pointer to first instance
                # if it is.
                if text_block[1] == entry[1] and text_block[2] == entry[2]\
                        and ptr_list.hi_bytes[index] == entry[3]:
                    prev_txt_ptr = ptr
                    new_txt_ptr = entry[4]
                    ptr_list.ptrs[index] = new_txt_ptr
                    try:
                        new_box_ptr = entry[5]
                        ptr_list.box_ptrs[index] = new_box_ptr
                    except IndexError:
                        pass
                    break
            else:
                try:
                    char_list_to_write = _encode_text_block(
                        text_block[1], curr_txt_offset)
                except UnicodeEncodeError as e:
                    print('Insert: Skipping file')
                    if called:
                        raise e
                    else:
                        sys.exit(4)

                # Adjust current offset location if battle text line
                # longer than original, OR adjust current offset location if text
                # in an OV will overflow its current text block.
                text_len = len(char_list_to_write) * 2
                if combat_ptrs:
                    orig_text_len = ptr_list.box_ptrs[index] - ptr
                    if text_len < orig_text_len:
                        padding = b'\x00' * (orig_text_len - text_len)
                        char_list_to_write.append(padding)
                    elif text_len > orig_text_len:
                        curr_txt_offset = os.path.getsize(file)
                elif extra_code_start is not None and \
                        (curr_txt_offset + text_len + 8 > extra_code_start):
                    curr_txt_offset = extra_code_end
                    extra_code_start = None
                elif ov_text_starts is not None:
                    if curr_txt_offset + text_len + 4 \
                            > OV_TEXT_ENDS[version][file_key][curr_text_block]:
                        if curr_text_block \
                                < len(OV_TEXT_ENDS[version][file_key]) - 1:
                            dead_bytes = OV_TEXT_ENDS[version][file_key][curr_text_block] - curr_txt_offset
                            for i in range(dead_bytes):
                                outf.write(b'\x00')
                            curr_text_block += 1
                            curr_txt_offset = OV_TEXT_STARTS[version][file_key][curr_text_block]
                        else:
                            print('Insert: Line "%s%s" exceeded end of last text block (offset %s)'
                                  'in %s.\n'
                                  'Insert: Text length needs to be shortened.' %
                                  (text_block[1], text_block[2].replace('00', ' '),
                                   hex(OV_TEXT_ENDS[version][file_key][curr_text_block]),
                                   file_key))
                            raise ValueError

                # Calculate and update the new text pointer.
                outf.seek(curr_txt_offset)
                prev_txt_ptr = ptr
                new_txt_ptr = ptr_list.calculate_pointer(outf, index)
                ptr_list.ptrs[index] = new_txt_ptr

                # Write char list to output file.
                for item in char_list_to_write:
                    outf.write(item)

                # If box pointer table exists, update current box pointer.
                if ptr_list.box_ptr_locs[index] is not None:
                    new_box_ptr = ptr_list.calculate_pointer(outf, index, 'box')
                    ptr_list.box_ptrs[index] = new_box_ptr
                    text_block.extend((ptr_list.hi_bytes[index], new_txt_ptr, new_box_ptr))
                else:
                    text_block.extend((ptr_list.hi_bytes[index], new_txt_ptr))
                dupe_check_text.append(text_block)

                # Write box dimensions, if present.
                if text_block[2]:
                    # Game hard codes box dimensions location in battle/cutscene files
                    # Always update values in original position for them.
                    outf.write(bytes.fromhex(text_block[2]))
                    if combat_ptrs:
                        outf.seek(ptr_list.box_ptrs[index])
                        outf.write(bytes.fromhex(text_block[2]))

                curr_txt_offset = outf.tell()

        # Fill out any unused space in an OVs text blocks with 00 bytes to
        # reduce compressed size.
        if ov_text_starts is not None:
            while curr_text_block < len(OV_TEXT_ENDS[version][file_key]):
                dead_bytes = OV_TEXT_ENDS[version][file_key][curr_text_block] - curr_txt_offset
                for i in range(dead_bytes):
                    outf.write(b'\x00')
                curr_text_block += 1
                try:
                    curr_txt_offset = OV_TEXT_STARTS[version][file_key][curr_text_block]
                    outf.seek(curr_txt_offset)
                except IndexError:
                    break

        # Write updated pointers to the output file.
        for index, ptr_loc in enumerate(ptr_list.ptr_locs):
            outf.seek(ptr_loc)
            outf.write(ptr_list.ptrs[index])
            if ptr_list.box_ptr_locs[index] is not None:
                outf.seek(ptr_list.box_ptr_locs[index])
                new_box_ptr = ptr_list.box_ptrs[index]

                # Create and write extra box pointer for single_ptr_tbl = 3.
                if ptr_list.box_tbl_starts[index] < ptr_list.tbl_starts[index]:
                    if ptr_list.tbl_starts[index] - ptr_list.box_tbl_starts[index] == 36:
                        new_box_ptr = b''.join((new_box_ptr[:2], b'\x00\x09'))
                    else:
                        outf.write(b''.join((new_box_ptr[:2], b'\x00\x13')))
                        new_box_ptr = b''.join((new_box_ptr[:2], b'\x01\x13'))
                outf.write(new_box_ptr)


def insert_all(list_file, disc_dict, version='USA'):
    """
    Inserts text to all files listed in a file list text file.

    Reads files from file list text file and adds all files with additional
    text inserting parameters to a list of files to insert text into. The
    function then loops through these and calls insert_text() on each one,
    inserting text from their respective CSVs. Each disc should have its
    own CSV, as output by dump_all().

    This function should be used with output txt file from id_file_type.
    This has already been done for each disc.

    Parameters
    ----------
    list_file : str
        Text file containing list of source files to insert text into.
    disc_dict : dict
        Dict containing information about disc image, directory structure,
        and game files
    version : str
        Version of the game to insert text for (default: 'USA')
    """

    print('\nInsert: Inserting script files')
    # For each disc in the file list, create an entry in script_dict with
    # the name of the corresponding CSV to insert text for that disc from.
    files_list = read_file_list(list_file, disc_dict, file_category='[PATCH]')['[PATCH]']
    if len(files_list) == 0:
        print('\nDump: No files found in file list.')
        sys.exit(7)

    script_dict = {}
    for key in list(files_list.keys()):
        file_parts = [x for x in os.path.split(disc_dict[key][2])]
        file_parts[1] = '.'.join((file_parts[1].replace(' ', '_'), 'csv'))
        script_dict[key] = os.path.join(*file_parts)

    # Loop through each disc in the file list and add all files with text insert
    # parameters to list of files to insert text into.
    scripts_inserted = 0
    total_scripts = 0
    files_to_insert = []
    for disc, disc_val in files_list.items():
        csv_file = script_dict[disc]

        update_box_dimensions(csv_file)

        # Loop through all files listed for each disc.
        for key, val in disc_val.items():
            parent_dir = '_'.join((os.path.splitext(key)[0], 'dir'))
            base_name = os.path.splitext(os.path.basename(key))[0]

            # Loop through all subfiles listed for each file.
            for file in val[1:]:
                # Convert file number to full file name with path.
                file_num = file[0]
                if 'OV_' in key.upper() or 'SCUS' in key.upper() \
                        or 'SCES' in key.upper() or 'SCPS' in key.upper():
                    block_range = process_block_range(file_num, base_name)
                    extension = os.path.splitext(key)[1]
                    file[0] = os.path.join(
                        parent_dir, ''.join((base_name, '_', block_range, extension)))
                else:
                    file[0] = os.path.join(
                        parent_dir, ''.join((base_name, '_', file_num, '.BIN')))

                # Convert all parameters to their appropriate data types,
                # append the appropriate csv_file to the end of the list
                # container with the file parameters, and append file to
                # list of files to isnert. Items with too few parameters
                # will not be added.
                try:
                    file[1] = int(file[1])
                    file[2] = [int(x, 16) for x in file[2].split(',')]
                    file[3] = [int(x, 16) for x in file[3].split(',')]
                    file[4] = [int(x) for x in file[4].split(',')]
                    if file[5] == '0' or file[5].lower() == 'none':
                        file[5] = None
                    else:
                        file[5] = [int(x, 16) for x in file[5].split(',')]
                    file.append(csv_file)
                    files_to_insert.append(file)
                except IndexError:
                    if val[1][1]:
                        print('Insert: Fewer than 6 parameters given in %s, file %s\n'
                              'Insert: Skipping file' % (key, file_num))
                    continue
                except ValueError:
                    print('Insert: Invalid value in "%s"\n'
                          'Insert: Skipping file' % file)
                    continue
                else:
                    scripts_inserted += 1
                finally:
                    if val[1][1]:
                        total_scripts += 1

    # Insert text into each file listed in files_to_insert.
    for file in sorted(files_to_insert):
        try:
            insert_text(file[0], file[6], file[2], file[3], file[4], file[5], version, True)
        except FileNotFoundError:
            print('Insert: File %s not found\nInsert: Skipping file' %
                  sys.exc_info()[1].filename)
            scripts_inserted -= 1
        except EOFError:
            scripts_inserted -= 1
        except UnicodeDecodeError:
            scripts_inserted -= 1

    print('Insert: Inserted %s of %s script files\n' %
          (scripts_inserted, total_scripts))
