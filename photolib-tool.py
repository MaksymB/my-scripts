#!/usr/local/bin/python3

import argparse
import datetime
import exifread
import glob
import os.path
import shutil
import struct
import subprocess
import sys

g_config_verbose = False
g_config_in_place = False
g_config_dry_run = False
g_config_exiftool = True

def mov_creation_date(file_path):
    if g_config_exiftool:
        output = subprocess.check_output(['exiftool',
                                          '-time:CreationDate',
                                          file_path])
        substrs = output.split(b': ')

        if len(substrs) != 2:
            if g_config_verbose:
                print("Can't parse exiftool output. Make sure it is installed")
            return None

        substrs2 = substrs[1].split(b'+')

        if len(substrs2) != 2 and len(substrs2) != 1:
            if g_config_verbose:
                print("Can't parse exiftool output. Make sure it is installed")
            return None

        return substrs2[0].strip().decode("utf-8").replace(':', '-')

    ATOM_HEADER_SIZE = 8

    # difference between Unix epoch and QuickTime epoch, in seconds
    EPOCH_ADJUSTER = 2082844800

    # open file and search for moov item
    f = open(file_path, "rb")
    while 1:
        atom_header = f.read(ATOM_HEADER_SIZE)
        if atom_header[4:8] == b'moov':
            break
        else:
            if len(atom_header) < 4:
                if g_config_verbose:
                    print("Can't read atom header: end of file")
                return None

            atom_size = struct.unpack(">I", atom_header[0:4])[0]
            f.seek(atom_size - 8, 1)

    # found 'moov', look for 'mvhd' and timestamps
    atom_header = f.read(ATOM_HEADER_SIZE)

    atom_header_name = atom_header[4:8]

    if atom_header_name == b'cmov':
        if g_config_verbose:
            print("moov atom is compressed")
        return None
    elif atom_header_name != b'mvhd':
        if g_config_verbose:
            print(f"expected to find 'mvhd' header, found '{atom_header}'")
        return None
    else:
        f.seek(4, 1)
        buf = f.read(4)

        if len(buf) < 4:
            if g_config_verbose:
                print("Can't read creation date: end of file")
            return None

        creation_date = datetime.datetime.utcfromtimestamp(
                            struct.unpack(">I", buf)[0] - EPOCH_ADJUSTER)
        # modification_date = struct.unpack(">I", f.read(4))[0]

        return str(creation_date).replace(':', '-')

def jpg_creation_date(file_path):
    f = open(file_path, 'rb')

    tags = exifread.process_file(f)

    f.close()

    date_time_tag = 'EXIF DateTimeOriginal'

    if date_time_tag in tags:
      return str(tags[date_time_tag]).replace(':', '-')

    return None

def move_file(source, target):
    print(f'{source} -> {target}')
    if not g_config_dry_run:
        shutil.move(source, target)

def find_files(input_paths, *masks):
    return list(filter(lambda p: os.path.isfile(p), input_paths)) + \
           [input_file for input_dir in filter(lambda p: os.path.isdir(p), input_paths)
                              for mask in masks
                              for input_file
                                  in glob.iglob(input_dir + '/**/' + mask,
                                                recursive=True)]

def process_files(input_files, extract_creation_date, ext):
    all_files = {}

    processed_files_count = 0

    for input_file_path in input_files:
        creation_date = extract_creation_date(input_file_path)
        if not creation_date in all_files:
            all_files[creation_date] = []
        all_files[creation_date].append(
            (input_file_path, os.path.getsize(input_file_path)))

    for (creation_date, same_creation_date_files) in all_files.items():
        if not creation_date:
            for (input_file_path, _) in same_creation_date_files:
                print(f'Warning: unknown creation date: {input_file_path}')
            continue

        # Sort from larger to smaller so untrimmed and higher resolution files
        # will come first in the list
        same_creation_date_files.sort(key=lambda tup: tup[1], reverse = True)

        count = 0
        for (input_file_path, _) in same_creation_date_files:
            (dir_path, input_file) = os.path.split(input_file_path)

            suffix = f' ({count})' if count > 0 else ''

            if g_config_in_place:
                output_file_path = os.path.join(dir_path,
                                                f'{creation_date}{suffix}.{ext}')

                if os.path.exists(output_file_path):
                    if input_file_path != output_file_path:
                        print(f'Cannot move {input_file_path} to {output_file_path}')
                else:
                    move_file(input_file_path, output_file_path)
                    processed_files_count += 1
            else:
                print('Error: out-of-place modification is not implemented')

            count += 1

    print(f'Processed {processed_files_count} file(s)')

def main():
    global g_config_verbose
    global g_config_in_place
    global g_config_dry_run
    global g_config_exiftool

    parser = argparse.ArgumentParser(
        description='My photo library maintenance tool')

    parser.add_argument('input_paths', metavar='input-path', type=str, nargs='+',
                        help='a directory with photos')
    parser.add_argument('--mov', action="store_true", default=False,
                        help='process .mov files')
    parser.add_argument('--jpg', action="store_true", default=False,
                        help='process .jpg files')
    parser.add_argument('--verbose', action="store_true", default=g_config_verbose,
                        help='verbose output')
    parser.add_argument('--in-place', action="store_true", default=g_config_in_place,
                        help='put output files next to the input files')
    parser.add_argument('--dry', action="store_true", default=g_config_dry_run,
                        help='dry run, print what is going to be done and exit')
    parser.add_argument('--no-exiftool', action="store_true", default=not g_config_exiftool,
                        help='don\'t use system exiftool (if not installed)')

    args = parser.parse_args()

    g_config_verbose = args.verbose
    g_config_in_place = args.in_place
    g_config_dry_run = args.dry
    g_config_exiftool = not args.no_exiftool

    input_paths = [os.path.normpath(p) for p in args.input_paths]

    bad_input_paths = list(filter(lambda p: not os.path.exists(p), input_paths))

    if bad_input_paths:
        print("Error: the following input directories are missing:")
        for bad_input_dir in bad_input_paths:
            print(f"  - {bad_input_dir}")

    if args.mov:
        mov_files = find_files(input_paths, '*.mov', '*.MOV')

        if g_config_verbose:
            print(f'Found {len(mov_files)} mov file(s)')

        process_files(mov_files, mov_creation_date, 'mov')

    if args.jpg:
        jpg_files = find_files(input_paths, '*.jpg', '*.jpeg', '*.JPG', '*.JPEG')

        if g_config_verbose:
            print(f'Found {len(jpg_files)} JPEG file(s)')

        process_files(jpg_files, jpg_creation_date, 'jpg')

main()
