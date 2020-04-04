from copy import deepcopy
import csv
from more_itertools import sort_together
import os
import re
import struct
import sys
from build_codec import *
from config_handler import read_file_list
from game_file_handler import process_block_range

is_insert = False

# Build custom standard and extended codecs for encoding/decoding LoD's
# text each time script is called. Allows for custom codecs that don't
# need to be located in the python codecs folder.
standard_table_end_val = build_codecs()
codecs.register(lod_codec.custom_search)
codecs.register(lod_ext_codec.getregentry)

OV_BOUND_PATTERN = {'BTTL.OV_': [re.compile(b'\xa0\xb1\x0f\x80')],
                    'S_BTLD.OV_': [re.compile(b'\xd8\xfb\x10\x80')],
                    'S_ITEM.OV_': [re.compile(b'\x74\x45\x11\x80'),
                                   re.compile(b'\x10\x7e\x11\x80'),
                                   re.compile(b'\x2c\x9b\x11\x80'),
                                   re.compile(b'\x10\xa1\x11\x80'),
                                   re.compile(b'\\x5c\xb8\x11\x80'),
                                   re.compile(b'\xf7\xf5\xec\xf7\xf7\xf7')],
                    'WMAP.OV_': [re.compile(b'\x10\xf7\x0e\x80')],
                    'SCUS_944.91': [re.compile(b'\x50\x04\x05\x80'),
                                    re.compile(b'\xe8\x0b\x05\x80'),
                                    re.compile(b'\x58\x18\x05\x80'),
                                    re.compile(b'\x68\x21\x05\x80')],
                    'SCUS_945.84': [re.compile(b'\x50\x04\x05\x80'),
                                    re.compile(b'\xe8\x0b\x05\x80'),
                                    re.compile(b'\x58\x18\x05\x80'),
                                    re.compile(b'\x68\x21\x05\x80')],
                    'SCUS_945.85': [re.compile(b'\x50\x04\x05\x80'),
                                    re.compile(b'\xe8\x0b\x05\x80'),
                                    re.compile(b'\x58\x18\x05\x80'),
                                    re.compile(b'\x68\x21\x05\x80')],
                    'SCUS_945.86': [re.compile(b'\x50\x04\x05\x80'),
                                    re.compile(b'\xe8\x0b\x05\x80'),
                                    re.compile(b'\x58\x18\x05\x80'),
                                    re.compile(b'\x68\x21\x05\x80')]}
ov_text_ends = {'BTTL.OV_': [],
                'S_BTLD.OV_': [],
                'S_ITEM.OV_': [],
                'WMAP.OV_': [],
                'SCUS_944.91': [],
                'SCUS_945.84': [],
                'SCUS_945.85': [],
                'SCUS_945.86': []}
END_FLAG = re.compile(b'\xff\xa0')
STARDUST_PATTERN = re.compile(b'\x1f\x00\x3b\x00\x49\x00\x4d\x00\x41\x00'
                              b'\x4a\x00\x3d\x00\x3c\x00\x00\x00\x05\xa7'
                              b'\x31\x00\x4c\x00\x39\x00\x4a\x00\x3c\x00'
                              b'\x4d\x00\x4b\x00\x4c\x00\x00\xa7\x00\x00'
                              b'\xff\xa0')
FUNDS_PATTERN = re.compile(b'\\x24\x00\x4d\x00\x46\x00\x3c\x00\x4b\x00'
                           b'\x00\x00\x00\xa8\x25\x00\xff\xa0')
FFCODE_PATTERN = re.compile(b'\xff\xff\xff\xff\\x09\x00\x00\x00\xff\xff\xff\xff')
DUMP_FLAG_DICT = {b'\xa0\xff': '<END>', b'\xa1\xff': '<LINE>',
                  b'\xa3\xff': '<WWWTS>', b'\xa5\x00': '<START0>',
                  b'\xa5\x01': '<START1>', b'\xa5\x02': '<START2>',
                  b'\xa5\x03': '<START3>', b'\xa5\x04': '<START4>',
                  b'\xa5\x05': '<START5>', b'\xa5\x0a': '<STARTA>',
                  b'\xa7\x00': '<TCLOSE>', b'\xa7\x05': '<SRED>',
                  b'\xa7\x08': '<CHOICE>', b'\xa8\x00': '<VAR0>',
                  b'\xa8\x01': '<VAR1>', b'\xa8\x02': '<VAR2>',
                  b'\xa8\x03': '<VAR3>', b'\xa8\x04': '<VAR4>',
                  b'\xa8\x08': '<VAR8>', b'\xb0\x00': '<SAUTO0>',
                  b'\xb0\x01': '<SAUTO1>', b'\xb0\x02': '<SAUTO2>',
                  b'\xb0\x03': '<SAUTO3>', b'\xb0\x04': '<SAUTO4>',
                  b'\xb0\x05': '<SAUTO5>', b'\xb0\x09': '<SAUTO9>',
                  b'\xb0\x0a': '<SAUTOA>', b'\xb0\x1e': '<SAUTO1E>',
                  b'\xb0\xff': '<SCUT>', b'\xb1\x01': '<FIRE>',
                  b'\xb1\x02': '<WATER>', b'\xb1\x03': '<WIND>',
                  b'\xb1\x04': '<EARTH>', b'\xb1\x05': '<LIGHT>',
                  b'\xb1\x06': '<DARK>', b'\xb1\x07': '<THNDR>',
                  b'\xb1\x08': '<NELEM>', b'\xb1\x09': '<NORM>',
                  b'\xb2\x00': '<SBAT>', b'\xa5\x0f': '<STARTF>'}
INSERT_FLAG_DICT = {'<END>': b'\xff\xa0', '<LINE>': b'\xff\xa1',
                    '<WWWTS>': b'\xff\xa3', '<START0>': b'\x00\xa5',
                    '<START1>': b'\x01\xa5', '<START2>': b'\x02\xa5',
                    '<START3>': b'\x03\xa5', '<START4>': b'\x04\xa5',
                    '<START5>': b'\x05\xa5', '<STARTA>': b'\x0a\xa5',
                    '<STARTF>': b'\x0f\xa5', '<TCLOSE>': b'\x00\xa7',
                    '<SRED>': b'\x05\xa7', '<CHOICE>': b'\x08\xa7',
                    '<VAR0>': b'\x00\xa8', '<VAR1>': b'\x01\xa8',
                    '<VAR2>': b'\x02\xa8', '<VAR3>': b'\x03\xa8',
                    '<VAR4>': b'\x04\xa8', '<VAR8>': b'\x08\xa8',
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

    def write_pointer(self, file, index):
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

        Returns
        -------
        byte string
            Little-endian 4-byte pointer.
        """

        if self.hi_bytes[index] is None:
            new_ptr = (file.tell() - self.tbl_starts[index]) >> 2
        elif self.hi_bytes[index] & 0x09000000 == 0x09000000:
            offset_adjustment = self.hi_bytes[index] ^ 0x09000000
            new_ptr = ((file.tell() - self.tbl_starts[index] + offset_adjustment)
                       >> 2) | 0x09000000
        elif self.hi_bytes[index] == 0x80000000:
            new_ptr = (file.tell() + self.offset_diffs[index]) \
                      | self.hi_bytes[index]
        else:
            new_ptr = (file.tell() + self.offset_diffs[index] ^ 0x110000)\
                      | self.hi_bytes[index]
        new_ptr = new_ptr.to_bytes(4, 'little')

        file.seek(self.ptr_locs[index])
        file.write(new_ptr)

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
            raw_ptr = file.read(4)
            if raw_ptr[3] == 0x09:
                test_bytes = file.read(8)
                if test_bytes == b'\x49\x00\x00\x00\x38\x01\xc0\x00':
                    offset_adjustment += 0x28
                else:
                    file.seek(file.tell()-0x28)
                    test_bytes = file.read(12)
                    if test_bytes ==\
                            b'\x38\x06\xc6\x00\x00\x00\x00\x00\x40\x00\x00\x0f':
                        offset_adjustment += 0x1c
                    else:
                        print('Invalid pointer at %d.' % start+curr_rel_offset)
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
            if ptr[3:] == b'\x80':
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

    half_word = None
    italics = False
    char_list = []
    box_dims = []

    # Loop through two-byte characters in text until end flag encountered.
    while half_word != b'\xa0\xff':
        # Characters where high byte is 0x00 need to be repacked as single
        # byte to decode properly.
        half_word = input_file.read(2)
        half_word_val = struct.unpack('<H', half_word)[0]
        if half_word_val <= 0xff:
            half_word = struct.pack('B', half_word_val)
        else:
            half_word = struct.pack('>H', half_word_val)

        # If the 2-byte sequence isn't a flag, decode and write the character.
        # Otherwise, write the text flag.
        if half_word not in DUMP_FLAG_DICT.keys():
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
                    char = half_word.decode('lod_extended', errors='strict')
                else:
                    char = half_word.decode('lod', errors='strict')
            except UnicodeDecodeError as e:
                print('Dump: Encountered unknown character %s at offset %s '
                      'while dumping file %s' %
                      (half_word, hex(input_file.tell() - 2), input_file.name))
                raise e
            else:
                char_list.append(char)
        else:
            if italics is True:  # Close italics if they haven't been already.
                char_list.append('}')
                italics = False

            char_list.append(DUMP_FLAG_DICT[half_word])
            if half_word == b'\xa1\xff':
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


def dump_text(file, csv_file, ptr_tbl_starts, ptr_tbl_ends,
              single_ptr_tbl=(False,), ov_text_starts=None, called=False):
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
        Folder to output CSV to.
    ptr_tbl_starts : int list
        List of starting offsets of pointer tables in file.
    ptr_tbl_ends : int list
        List of ending offsets of pointer tables in file.
    single_ptr_tbl : boolean list
        Indicates whether pointer tables are dual (text and box tables)
        (default: (False, )).
    ov_text_starts : int list
        List of starting offsets of text blocks in OV_ files (default: None).
    called : boolean
        Indicates whether function was called from _dump_helper()
        (default: False).
    """

    global is_insert
    is_insert = False
    file_size = os.path.getsize(file)
    basename = os.path.splitext(os.path.basename(file))[0]
    csv_output = []

    with open(file, 'rb') as inf:
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


def dump_additions(file, csv_file, tbl_start=(0x3424c,),
                   tbl_end=(0x34405,), called=False):
    """
    Dumps addition text from BTTL.OV_.

    Additions in BTTL.OV_ are a special case of text dumping, as they do not
    use pointer tables, and are encoded in ASCII rather than LoD's own
    encoding. This function reads the full additions text, then splits
    it by character. Each character's additions are ASCII decoded and
    written to their own row in a CSV, along with the file name and entry
    number. Additions can be written to the same CSV as all other text.
    The CSV file will be initialized either by the command prompt interface
    or the dump_all() function so that functionality in this function is
    consistent regardless of whether it is used singly or as part of a batch
    process.

    Parameters
    ----------
    file : str
        Full path name of the file from which to dump text.
    csv_file : str
        Folder to output CSV to.
    tbl_start : int list
        Starting offset of additions text in file. Single value, but formatted
        as list for consistency with dump_text() (default: (0x3424c,)).
    tbl_end : int list
        Ending offset of additions text in file. Single value, but formatted
        as list for consistency with dump_text() (default: (0x34405,)).
    called : boolean
        Indicates whether function was called from _dump_helper()
        (default: False).
    """

    basename = os.path.splitext(os.path.basename(file))[0]
    basename = '_'.join((basename, 'additions'))
    csv_output = []

    try:
        with open(file, 'rb') as inf:
            inf.seek(tbl_start[0])
            addition_block_size = tbl_end[0] - tbl_start[0]
            additions_block = inf.read(addition_block_size)
    except FileNotFoundError as e:
        if called:
            raise e
        else:
            print('Dump: File %s not found\nDump: Skipping file' %
                  sys.exc_info()[1].filename)
            return

    additions_list = [x for x in additions_block.split(b'\x00\x00') if x]
    for i, bytestr in enumerate(additions_list, start=1):
        char_list = []
        for byte in bytestr:
            if byte == 0x00:
                char_list.append('\n')
            else:
                char_list.append(byte.to_bytes(1, 'little').decode('ascii'))

        string = ''.join(char_list)
        csv_row = [basename, i, string, string]
        csv_output.append(csv_row)

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
    text dumping parameters to a list of file to dump text from. A new blank
    CSV is created for each disc that contains files to dump. The function
    then loops through these and calls either dump_text() or dump_additions()
    on each one, dumping text to their respective CSVs.

    This function should be used with output txt file from id_file_type.
    This has already been done for each disc.

    Parameters
    ----------
    list_file : str
        Text file containing list of source files to extract from/decompress.
    disc_dict : dict
        Dict containing information about disc image, directory structure,
        and game files
    """
    print('\nDump: Dumping script files')

    # For each disc in the file list, create an entry in script_dict with
    # the name of the corresponding CSV to dump text for that disc to.
    files_list = read_file_list(list_file, disc_dict,
                                file_category='[PATCH]')['[PATCH]']
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
                    temp = []
                    for x in file[4].split(','):
                        if x == '1' or x.lower() == 'true':
                            temp.append(True)
                        elif x == '0' or x.lower() == 'false':
                            temp.append(False)
                        else:
                            raise ValueError
                    file[4] = deepcopy(temp)
                    if file[5] == '0' or file[5].lower() == 'none':
                        file[5] = None
                    else:
                        file[5] = [int(x, 16) for x in file[5].split(',')]
                    file.append(csv_file)
                    files_to_dump.append(file)
                except IndexError:
                    if len(file) == 4:
                        scripts_dumped += 1
                        file.append(csv_file)
                        files_to_dump.append(file)
                    else:
                        if val[1][1]:
                            print('Dump: Fewer than 5 parameters given in %s, file %s\n'
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
            if len(file) == 5:
                dump_additions(file[0], file[4], file[2], file[3], True)
            else:
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
