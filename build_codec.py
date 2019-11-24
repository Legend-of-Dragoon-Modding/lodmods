import lod_codec
import lod_ext_codec


def build_codecs():
    with open('lod.tbl', 'r') as font_table:
        standard_lookup_table = ''
        extended_lookup_table = ''
        i = -1
        for line in font_table:
            standard_lookup_table = ''.join((standard_lookup_table, line[0]))

            if line[0] == ' ':
                extended_lookup_table = ''.join((extended_lookup_table, line[0]))
            else:
                extended_lookup_table = ''.join((extended_lookup_table, '\uffff'))

            if line.strip('\n') != '':
                i += 1
            else:
                break

        standard_table_end_val = i
        lod_codec.settables(standard_lookup_table.strip('\n'))

        extended_lookup_table = extended_lookup_table[:i+1]
        for line in font_table:
            extended_lookup_table = ''.join((extended_lookup_table, line[0]))
        else:
            lod_ext_codec.settables(extended_lookup_table.strip('\n'))

    return standard_table_end_val


if __name__ == '__main__':
    build_codecs()
