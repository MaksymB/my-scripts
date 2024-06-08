#!/usr/bin/python3

import argparse
import datetime
import exifread
import glob
import os.path
import shutil
import struct
import subprocess
import sys

g_config_verbose  = False
g_config_dry_run  = False
g_config_exiftool = True
g_config_ffprobe  = False
g_config_dune     = False
g_config_skip_dune = False
g_config_conversion_preset = "fast"

def get_date_by_exiftool(file_path, date_name):
    output = subprocess.check_output(['exiftool',
                                      '-ee',
                                      f'-time:{date_name}',
                                      file_path])
    substrs = output.split(b': ')

    if len(substrs) < 2:
        if g_config_verbose:
            print("Can't parse exiftool output. Make sure it is installed")
        return None

    substrs2 = substrs[1][:19].split(b'+')

    if len(substrs2) != 2 and len(substrs2) != 1:
        if g_config_verbose:
            print("Can't parse exiftool output. Make sure it is installed")
        return None

    return substrs2[0].strip().decode("utf-8").replace(':', '-')

def get_date_by_ffprobe(file_path):
    output = subprocess.check_output(['ffprobe',
                                      '-v', 'quiet',
                                      '-select_streams', 'v:0',
                                      '-show_entries', 'stream_tags=creation_time',
                                      '-of', 'default=noprint_wrappers=1:nokey=1',
                                      file_path])

    try:
        # Convert from b'2016-03-09T05:47:50.000000Z\n'
        #           to '2016-03-09 05:47:50'
        return output.split(b'.')[0].decode("utf-8").replace(':', '-').replace('T', ' ')
    except Exception as e:
        return None

def get_rotation_by_ffprobe(file_path):
    output = subprocess.check_output(['ffprobe',
                                      '-v', 'quiet',
                                      '-select_streams', 'v',
                                      '-show_entries', 'stream_side_data=rotation',
                                      '-of', 'default=noprint_wrappers=1:nokey=1',
                                      file_path])
    return output.decode("utf-8").strip()

def get_codec_by_ffprobe(file_path, stream_name):
    output = subprocess.check_output(['ffprobe',
                                      '-v', 'quiet',
                                      '-select_streams', stream_name,
                                      '-show_entries', 'stream=codec_name',
                                      '-of', 'default=noprint_wrappers=1:nokey=1',
                                      file_path])
    return output.decode("utf-8").strip()

def fix_by_ffmpeg(source, target, skip_video_conversion=False):
    if not os.path.exists(target):
        audio_codec = get_codec_by_ffprobe(source, 'a')
        video_codec = get_codec_by_ffprobe(source, 'v')
        rotation = get_rotation_by_ffprobe(source)

        fix_audio = False
        fix_video = False
        audio_settings = ['-codec:a', 'copy']
        video_settings = ['-codec:v', 'copy']
        if audio_codec != "aac":
            audio_settings = ['-codec:a', 'aac']
            fix_audio = True

        if video_codec != 'h264':
            print(f'WARNING: codec is not h264. Codec is {video_codec}')

        if rotation != "":
            print(f'WARNING: rotation detected {rotation}')

        if rotation != "" or video_codec != 'h264':
            if skip_video_conversion:
                return True
            else:
                video_settings = ['-codec:v', 'libx264', '-crf', '18', '-preset', g_config_conversion_preset]
                fix_video = True

        if not fix_video and not fix_audio:
            return False

        print(f'{source} -> {target} [Audio fix: {fix_audio}, video fix: {fix_video}]')

        if not g_config_dry_run:
            subprocess.check_output(['ffmpeg',
                                     '-hide_banner',
                                     '-loglevel', 'error',
                                     '-i', source,
                                     '-map_metadata', '0'] + audio_settings + video_settings + [target])

            subprocess.check_output(['exiftool',
                                     '-ee',
                                     '-tagsfromfile', source,
                                     '-gps*',
                                     target])

            move_file(source, target + '.orig.mov')

        return True
    else:
        print(f'Cannot move {source} to {target}')
        return False

def mov_creation_date(file_path):
    if g_config_ffprobe:
        return get_date_by_ffprobe(file_path)

    if g_config_exiftool:
        original_Date_time = get_date_by_exiftool(file_path, 'DateTimeOriginal')
        if original_Date_time:
            return original_Date_time

        creation_date = get_date_by_exiftool(file_path, 'CreationDate')
        if creation_date:
            return creation_date

        return get_date_by_exiftool(file_path, 'CreateDate')


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

def process_files(input_files, extract_creation_date, ext, output_path, fix_av_codecs):
    all_files = {}

    processed_files_count = 0

    checked_files_count = 0
    for input_file_path in input_files:
        creation_date = extract_creation_date(input_file_path)
        if not creation_date in all_files:
            all_files[creation_date] = []
        all_files[creation_date].append(
            (input_file_path, os.path.getsize(input_file_path)))
        checked_files_count += 1
        print(f'{checked_files_count}/{len(input_files)} checked')

    files_count = 0
    for (creation_date, same_creation_date_files) in all_files.items():
        files_count += 1
        print(f'[{files_count}/{len(all_files.items())}] {input_file_path}')

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

            if output_path:
                if not os.path.exists(output_path):
                    os.mkdir(output_path)

                output_file_path = os.path.join(output_path,
                                                f'{creation_date}{suffix}.{ext}')
            else:
                output_file_path = os.path.join(dir_path,
                                                f'{creation_date}{suffix}.{ext}')


            if os.path.exists(output_file_path):
                if input_file_path != output_file_path:
                    print(f'Cannot move {input_file_path} to {output_file_path}')
            else:
                if fix_av_codecs:
                    if not fix_by_ffmpeg(input_file_path, output_file_path, g_config_skip_dune):
                        move_file(input_file_path, output_file_path)
                else:
                    move_file(input_file_path, output_file_path)

                processed_files_count += 1

            count += 1

    print(f'Processed {processed_files_count} file(s)')

def main():
    global g_config_verbose
    global g_config_dry_run
    global g_config_exiftool
    global g_config_ffprobe
    global g_config_dune
    global g_config_skip_dune
    global g_config_conversion_preset

    parser = argparse.ArgumentParser(
        description='My photo library maintenance tool')

    parser.add_argument('input_paths', metavar='input-path', type=str, nargs='+',
                        help='a directory with photos')
    parser.add_argument('--mov', action="store_true", default=False,
                        help='process only .mov files')
    parser.add_argument('--jpg', action="store_true", default=False,
                        help='process only .jpg files')
    parser.add_argument('--verbose', action="store_true", default=g_config_verbose,
                        help='verbose output')
    parser.add_argument('--in-place', action="store_true", default=False,
                        help='put output files next to the input files')
    parser.add_argument('--dry', action="store_true", default=g_config_dry_run,
                        help='dry run, print what is going to be done and exit')
    parser.add_argument('--no-exiftool', action="store_true", default=not g_config_exiftool,
                        help='don\'t use system exiftool (if not installed)')
    parser.add_argument('--ffprobe', action="store_true", default=g_config_ffprobe,
                        help='use system ffprobe tool')
    parser.add_argument('--dune', action="store_true", default=g_config_dune,
                        help='convert mov files to be playable by Dune HD H1 player')
    parser.add_argument('--skip-dune', action="store_true", default=g_config_skip_dune,
                        help='skip files that cannot be playable by Dune HD H1 player')
    parser.add_argument('--preset', action="store", dest="preset", type=str,
                        help='video conversion preset for Dune HD H1 player')
    parser.add_argument('--output', action="store", dest="output_dir", type=str,
                        help='the output directory path')

    args = parser.parse_args()

    if (not args.output_dir) == (not args.in_place):
        print("error: one (and only one) of the following arguments is required:",
              "--in-place, --output")
        sys.exit(0)

    g_config_verbose = args.verbose
    g_config_dry_run = args.dry
    g_config_exiftool = not args.no_exiftool
    g_config_ffprobe = args.ffprobe
    g_config_dune = args.dune or args.skip_dune
    g_config_skip_dune = args.skip_dune

    if args.preset != None:
        g_config_conversion_preset = args.preset

    if g_config_dune:
        print(f'Video conversion preset: {g_config_conversion_preset}')

    input_paths = [os.path.normpath(p) for p in args.input_paths]

    bad_input_paths = list(filter(lambda p: not os.path.exists(p), input_paths))

    if bad_input_paths:
        print("Error: the following input directories are missing:")
        for bad_input_dir in bad_input_paths:
            print(f"  - {bad_input_dir}")

    all_formats = not args.mov or not args.jpg

    if args.mov or all_formats:
        mov_files = find_files(input_paths, '*.mov', '*.MOV', '*.mp4', '*.MP4', '*.3gp', '*.3GP', '*.MTS', '*.mts')

        if g_config_verbose:
            print(f'Found {len(mov_files)} mov file(s)')

        process_files(mov_files, mov_creation_date, 'mov', args.output_dir, g_config_dune)

    if args.jpg or all_formats:
        jpg_files = find_files(input_paths, '*.jpg', '*.jpeg', '*.JPG', '*.JPEG')

        if g_config_verbose:
            print(f'Found {len(jpg_files)} JPEG file(s)')

        process_files(jpg_files, jpg_creation_date, 'jpg', args.output_dir, False)

main()
