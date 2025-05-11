#!/usr/bin/python3

import argparse
import hashlib
import os
import shutil
import struct
import xml.etree.ElementTree as ET
import zipfile
import difflib

######### python-ips ##########################################################
## A slightly modified piece of python-ips from here:
## https://github.com/meunierd/python-ips
##
def apply_patch(patchpath, filepath):
    patch_size = os.path.getsize(patchpath)
    patchfile = open(patchpath, 'rb')
    target = open(filepath, 'r+b')

    if patchfile.read(5) != b'PATCH':
        raise Exception('Invalid patch header.')

    def unpack_int(s):
        (ret,) = struct.unpack_from('>I', b'\x00' * (4 - len(s)) + s)
        return ret

    # Read First Record
    r = patchfile.read(3)
    while patchfile.tell() not in [patch_size, patch_size - 3]:
        # Unpack 3-byte pointers.
        offset = unpack_int(r)
        # Read size of data chunk
        r = patchfile.read(2)
        size = unpack_int(r)

        if size == 0:  # RLE Record
            r = patchfile.read(2)
            rle_size = unpack_int(r)
            data = patchfile.read(1) * rle_size
        else:
            data = patchfile.read(size)

        if offset >= 0:
            # Write to file
            target.seek(offset)
            target.write(data)
        # Read Next Record
        r = patchfile.read(3)

    if patch_size - 3 == patchfile.tell():
        trim_size = unpack_int(patchfile.read(3))
        target.truncate(trim_size)

    # Cleanup
    target.close()
    patchfile.close()

##########################################

CONST_UNKNOWN_REGION = 'Unknown'
CONST_BAD_ROM = 'Bad'
CONST_PARENT_CLONE = 'PARENT'

CONST_LICENSED = "Licensed"
CONST_UNLICENSED = "Unlicensed"
CONST_PIRATE = "Pirate"
CONST_HOMEBREW = "Homebrew"

LICENSES = {
    None: CONST_LICENSED,
    "0":  CONST_UNLICENSED,
    "1":  CONST_LICENSED,
    "2":  CONST_PIRATE,
    "3":  CONST_HOMEBREW
}

PRIORITY_REGIONS = ['USA', 'Japan', 'Europe']

def find_db_export_archive(directory):
    db_archives = list(filter(lambda p : p.endswith(".zip") and "(DB Export)" in p, os.listdir(directory)))

    if len(db_archives) == 0:
        raise FileNotFoundError("DB arhive not found.")

    if len(db_archives) > 1:
        db_archives.sort(reverse = True)
        print(f"WARNING: More than one DB archive found:")
        for db_archive in db_archives:
            print(f"  - {db_archive}")
        print(f"The most recent will be used: {db_archives[0]}\n")

    return os.path.join(directory, db_archives[0])

def find_private_dat_archive(directory):
    dat_archives = list(filter(lambda p : p.endswith(".zip") and "(Private)" in p, os.listdir(directory)))

    if len(dat_archives) == 0:
        return None

    if len(dat_archives) > 1:
        dat_archives.sort(reverse = True)
        print(f"WARNING: More than one private dat archive found:")
        for dat_archive in dat_archives:
            print(f"  - {dat_archive}")
        print(f"The most recent will be used: {dat_archives[0]}\n")

    return os.path.join(directory, dat_archives[0])

def extract_xml_from_archive(archive_path):
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        xml_files = [name for name in zip_ref.namelist() if name.endswith('.xml')]
        if len(xml_files) != 1:
            raise FileNotFoundError("The archive does not contain exactly one XML file.")
        with zip_ref.open(xml_files[0]) as xml_file:
            return xml_file.read()

def parse_xml(xml_content):
    return ET.fromstring(xml_content)

def build_game_dict(root, args):
    game_dict = {}
    sha1_to_game_id = {}
    for game in root.findall('game'):
        full_name = game.attrib.get('name')
        if args.skip_common_prefix:
            if full_name.startswith(args.skip_common_prefix):
                full_name = full_name[len(args.skip_common_prefix):]

        for archive in game.findall('archive'):
            game_id = archive.attrib.get('number')
            if game_id not in game_dict:
                game_regions = [r for r in archive.attrib.get('region').split(', ') if r != CONST_UNKNOWN_REGION]
                game_regions.sort()
                game_license =  LICENSES[archive.attrib.get('licensed')]
                if args.no_unlicensed and game_license != CONST_LICENSED:
                    continue
                bios = archive.attrib.get('bios') == '1'
                if bios and args.no_bios:
                    continue
                clone = archive.attrib.get('clone')
                game_dict[game_id] = {
                    'full_name': full_name,
                    'name': archive.attrib.get('name'),
                    'clone': CONST_PARENT_CLONE if clone == None or str(clone).lower() == 'p' else clone,
                    'clones': [],
                    'devstatus': archive.attrib.get('devstatus'),
                    'bios': bios,
                    'languages': archive.attrib.get('languages').split(','),
                    'license': game_license,
                    'regions': game_regions,
                    'version1': archive.attrib.get('version1'),
                    'version2': archive.attrib.get('version2'),
                    'files': {}
                }
            for source in game.findall('source') + game.findall('release'):
                for file in source.findall('file'):
                    format = file.attrib.get('format')
                    file_size = int(file.attrib.get('size'))
                    file_item = file.attrib.get('item')
                    ext = file.attrib.get('extension')
                    force_file_name = file.attrib.get('forcename')
                    if force_file_name:
                        print(f"Force file name: {force_file_name}")
                    if format == "Headerless" and not args.with_headerless:
                        continue
                    sha1 = file.attrib.get('sha1')
                    details = source.find('details')
                    if details == None:
                        raise Exception("Game details not found")
                    rominfo = details.attrib.get('rominfo')
                    if args.no_bad_roms and rominfo == CONST_BAD_ROM:
                        continue
                    regions = details.attrib.get('region').split(', ')
                    sections = [details.attrib.get('section')]
                    file_info = {
                        'format': format,
                        'expected_name': full_name,
                        'file_size': file_size,
                        'regions': [r for r in regions if r != CONST_UNKNOWN_REGION],
                        'sections': [s for s in sections if s != None],
                        'rominfo': rominfo,
                        'package_path': None,
                        'file_name': None,
                    }

                    if force_file_name:
                        file_info['expected_name'] = force_file_name
                    else:
                        n = full_name
                        if file_item != None:
                            n = f"{n} ({file_item})"
                        if ext != None:
                            n = f"{n}.{ext}"
                        file_info['expected_name'] = n

                    if not sha1 in game_dict[game_id]['files']:
                        game_dict[game_id]['files'][sha1] = file_info
                    else:
                        fi = game_dict[game_id]['files'][sha1]
                        if fi['format'] != file_info['format']:
                            if args.verbose:
                                print(f"WARNING: Inconsistend rom format in '[{game_id}] {full_name}'")
                                print(f"  - ({fi['format']}/{file_info['format']})\n")
                            fi['format'] += "/" + file_info['format']
                            #raise Exception("Format mismatch")
                        for r in file_info['regions']:
                           if not r in fi['regions']:
                               fi['regions'].append(r)
                               fi['regions'].sort()
                        for s in file_info['sections']:
                           if not s in fi['sections']:
                               fi['sections'].append(s)
                               fi['sections'].sort()
                        if fi['rominfo'] == None:
                            fi['rominfo'] = rominfo
                        elif file_info['rominfo'] != None and fi['rominfo'] != file_info['rominfo']:
                            print(f"WARNING: Rominfo mismatch in '[{game_id}] {full_name}'")
                            print(f"  - ({fi['rominfo']}/{file_info['rominfo']})\n")
                            fi['rominfo'] += "/" + file_info['rominfo']
                    if not sha1 in sha1_to_game_id:
                        sha1_to_game_id[sha1] = [game_id]
                    elif sha1_to_game_id[sha1] != game_id:
                        sha1_to_game_id[sha1].append(game_id)

    bad_clones = 0
    bad_clone_sources = 0
    for game_id, info in game_dict.items():
        clone = info['clone']
        if clone == CONST_PARENT_CLONE:
            continue
        if clone in game_dict:
            clone_source = game_dict[clone]
            clone_source['clones'].append(game_id)
            if clone_source['clone'] != CONST_PARENT_CLONE:
                if args.verbose:
                    print(f"WARNING: Non-parent clone has clones: [{clone}] {clone_source['full_name']}\n")
                bad_clone_sources += 1
        else:
            if args.verbose:
                print(f"WARNING: Clone source not found.")
                print(f"  - {info['full_name']}")
                print(f"  - Clone Source ID: {clone}\n")
            bad_clones += 1
            # Correct bad clone source reference
            info['clone'] = CONST_PARENT_CLONE

    return game_dict, sha1_to_game_id, bad_clones

def print_game_name_with_clones(game_dict, game_id, prefix):
    info = game_dict[game_id]
    print(f"{prefix}- [{game_id}] {info['full_name']}")
    for clone_game_id in info['clones']:
        print_game_name_with_clones(game_dict, clone_game_id, prefix + "  ")

def compute_sha1(data):
    sha1 = hashlib.sha1()
    sha1.update(data)
    return sha1.hexdigest()

def test_roms_package(package_path, sha1_to_game_id, game_dict):
    tested_roms_count = 0
    unknown_roms_count = 0
    wrong_rom_names_count = 0
    with zipfile.ZipFile(package_path, 'r') as zip_ref:
        for zip_info in zip_ref.infolist():
            if zip_info.is_dir():
                continue
            with zip_ref.open(zip_info) as file:
                file_data = file.read()
                sha1 = compute_sha1(file_data)
                tested_roms_count += 1
                if sha1 in sha1_to_game_id:
                    actual_file_name = os.path.basename(zip_info.filename)
                    game_ids = sha1_to_game_id[sha1]
                    game_id = game_ids[0]
                    if len(game_ids) > 1:
                        ns = dict([(info['files'][sha1]['expected_name'], id) for id, info in game_dict.items() if id in game_ids])
                        close_matches = difflib.get_close_matches(actual_file_name, ns.keys())
                        if len(close_matches) > 0:
                            game_id = ns[close_matches[0]]
                        else:
                            game_id = list(ns.values())[0]

                    info = game_dict[game_id]

                    # Update game's file info
                    info['files'][sha1]['package_path'] = package_path
                    info['files'][sha1]['file_name'] = zip_info.filename

                    expected_file_name = info['files'][sha1]['expected_name']

                    if actual_file_name == expected_file_name:
                        print(f"[+] {package_path}/{zip_info.filename}")
                    else:
                        wrong_rom_names_count += 1
                        print(f"[~] {package_path}/{zip_info.filename}")
                        print(f"  - Wrong file name. Expected '{expected_file_name}'")
                else:
                    unknown_roms_count += 1
                    print(f"[-] {package_path}/{zip_info.filename}")
                    print(f"  - Not found in the DB: {sha1}")

    print()
    return tested_roms_count, unknown_roms_count, wrong_rom_names_count

def export_file(package_path, file_name, export_dir, export_file_name):
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)

    export_file_path = os.path.join(export_dir, export_file_name)

    print(f"Export: {export_file_path}")
    with zipfile.ZipFile(package_path, 'r') as zip_ref:
        with zip_ref.open(file_name) as source_file:
            with open(export_file_path, 'wb') as target_file:
                target_file.write(source_file.read())

    return export_file_path

def get_main_reg_subdir(regions, rest_of_the_world):
    if 'World' in regions:
        return PRIORITY_REGIONS[0]
    for r in PRIORITY_REGIONS:
        if r in regions:
            return r
    return rest_of_the_world

def main():
    parser = argparse.ArgumentParser(description="Command line tool to read and manipulate XML metadata from a DB Export archive.")
    parser.add_argument('directory', type=str, help="Path to the directory containing the archive")
    parser.add_argument('--export', type=str, help="Export all known ROMs to the given directory.")
    parser.add_argument('--patch', type=str, help="Patch roms by the given list of patches.")
    parser.add_argument('--split-by-abc', action='store_true', help="Sort ROMs into ABC directories on export.")
    parser.add_argument('--split-by-license', action='store_true', help="Sort ROMs into Licensed/Unlicensed directories on export.")
    parser.add_argument('--split-by-size-32mb', action='store_true', help="Sort ROMs into Small/Large directories on export.")
    parser.add_argument('--split-by-main-reg', action='store_true', help="Split ROMS by main regions USA+World/Japan/Europe/ROTW")
    parser.add_argument('--split-bioses', action='store_true', help="Sort BIOS ROMs into BIOS directory on export.")
    parser.add_argument('--verbose', action='store_true', help="Show all warnings")
    parser.add_argument('--print', action='store_true', help="Print games list with details")
    parser.add_argument('--list', action='store_true', help="List games grouped by unique titles")
    parser.add_argument('--summary', action='store_true', help="Print library summary")
    parser.add_argument('--test-packages', action='store_true', help="Test all ROMs packages against the database")
    parser.add_argument('--no-bad-roms', action='store_true', help="Skip bad roms")
    parser.add_argument('--no-unlicensed', action='store_true', help="Skip unlicensed games")
    parser.add_argument('--no-bios', action='store_true', help="Skip BIOS ROMs")
    parser.add_argument('--with-headerless', action='store_true', help="Include headerless roms")
    parser.add_argument('--skip-common-prefix', type=str, help="Skip common prefix in full file names.")

    args = parser.parse_args()

    archive_path = find_db_export_archive(os.path.join(args.directory, '.db'))
    private_dat_archive_path = find_private_dat_archive(os.path.join(args.directory, '.db'))
    xml_content = extract_xml_from_archive(archive_path)
    root = parse_xml(xml_content)

    game_dict, sha1_to_game_id, bad_clones = build_game_dict(root, args)

    if args.list:
        for game_id, info in game_dict.items():
            if info['clone'] == CONST_PARENT_CLONE:
                print_game_name_with_clones(game_dict, game_id, "")
    print()

    if args.print:
        for game_id, info in game_dict.items():
            print(f"[{game_id}] {info['full_name']}")
            print(f"  - name:         {info['name']}")
            print(f"  - languages:    {info['languages']}")
            print(f"  - license:      {info['license']}")
            print(f"  - regions:      {info['regions']}")

            clone = info['clone']
            if clone == CONST_PARENT_CLONE:
                print(f"  - clone:        {clone}")
            else:
                print(f"  - clone:        [{clone}] ({game_dict[clone]['full_name']})")
            print(f"  - clones:       {info['clones']}")
            print(f"  - devstatus:    {info['devstatus']}")
            print(f"  - bios:         {info['bios']}")
            print(f"  - version1:     {info['version1']}")
            print(f"  - version2:     {info['version2']}")
            for sha1, f in info['files'].items():
                print(f"  - file {sha1}:")
                print(f"      - format:   {f['format']}")
                print(f"      - exp_name: {f['expected_name']}")
                print(f"      - regions:  {f['regions']}")
                print(f"      - sections: {f['sections']}")
                print(f"      - rominfo:  {f['rominfo']}")

    if args.summary or args.print or args.list:
        unique_titles = 0
        region_to_game_count = {}
        lang_to_game_count = {}
        for _, info in game_dict.items():
            if info['clone'] == CONST_PARENT_CLONE:
                unique_titles += 1

            region = ', '.join(info['regions']) if info['license'] == CONST_LICENSED else "Unlicensed"
            if not region in region_to_game_count:
                region_to_game_count[region] = 0
            region_to_game_count[region] += 1

            for lang in info['languages']:
                if not lang in lang_to_game_count:
                    lang_to_game_count[lang] = 0
                lang_to_game_count[lang] += 1

        print("\n--------------------")
        print(f"Number of games: {len(game_dict.items())}")
        print(f"Unique titles:   {unique_titles}")
        print(f"Bad clone refs:  {bad_clones}")
        print()

        print("Games per region:")
        for region, count in region_to_game_count.items():
            print(f"  - {region} {' ' * (20 - len(region))}: {count}")
        print()

        print("Games per language:")
        for lang, count in lang_to_game_count.items():
            print(f"  - {lang} {' ' * (20 - len(lang))}: {count}")
        print()

    if args.test_packages or args.export or args.patch:
        tested_roms_count = 0
        unknown_roms_count = 0
        wrong_rom_names_count = 0
        private_packages_ignored = 0

        for root, dirs, files in os.walk(args.directory):
            dirs[:] = [d for d in dirs if d != '.db']
            for file in files:
                if file.endswith('.zip'):
                    zip_path = os.path.join(root, file)
                    if not "Private" in file:
                        trc, urc, wrc = test_roms_package(zip_path, sha1_to_game_id, game_dict)
                    else:
                        private_packages_ignored += 1
                    tested_roms_count += trc
                    unknown_roms_count += urc
                    wrong_rom_names_count += wrc

        print(f"Tested roms:          {tested_roms_count}")
        print(f"  - Unknown roms:     {unknown_roms_count}")
        print(f"  - Wrong rom names:  {wrong_rom_names_count}")
        print(f"  - Ignored packages: {private_packages_ignored}")
        print()


    if args.patch:
        tree = ET.parse(args.patch)
        root = tree.getroot()
        output = root.find('output').text

        # Iterate through each <rom> element
        for rom in root.findall('rom'):
            sha1 = rom.find('sha1').text
            patch = rom.find('patch').text
            print(f"SHA1: {sha1}, Patch: {patch}")
            if sha1 in sha1_to_game_id:
                info = game_dict[sha1_to_game_id[sha1][0]]
                for file_sha1, f in info['files'].items():
                    if file_sha1 == sha1:
                        target_name, target_ext = os.path.splitext(f['expected_name'])
                        patch_name, _ = os.path.splitext(os.path.basename(patch))
                        patched_file_name = f"{target_name} ({patch_name}){target_ext}"
                        print("Patching: ", patched_file_name)
                        exported_file = export_file(f['package_path'], f['file_name'], output, patched_file_name)
                        apply_patch(patch, exported_file)
            else:
                print("Not found: ", sha1)

    if args.export:
        export_path = args.export
        if os.path.exists(export_path):
            if os.listdir(export_path):
                #raise FileExistsError(f"The path '{export_path}' already exists and is not empty.")
                shutil.rmtree(export_path)
                os.makedirs(export_path)

        # Figure out what is Rest of the World
        rest_of_the_world = 'ROTW'
        if args.split_by_main_reg:
            other_regions = []
            for game_id, info in game_dict.items():
                for _, f in info['files'].items():
                    if f['file_name'] != None:
                        for r in info['regions']:
                            if r != 'World' and not r in PRIORITY_REGIONS:
                                if not r in other_regions:
                                    other_regions.append(r)
            if len(other_regions) == 1:
                rest_of_the_world = other_regions[0]

        files_to_export = {}
        exported_files = 0
        for game_id, info in game_dict.items():
            for _, f in info['files'].items():
                if f['file_name'] != None:
                    target_file_name = f['expected_name']

                    # Figure out which sub-directories need to be added
                    target_dir_path = export_path
                    if args.split_bioses and info['bios']:
                        target_dir_path = os.path.join(target_dir_path, 'BIOS')
                    else:
                        if args.split_by_license:
                            sub_dir_name = CONST_UNLICENSED
                            if info['license'] == CONST_LICENSED:
                                sub_dir_name = CONST_LICENSED
                            target_dir_path = os.path.join(target_dir_path, sub_dir_name)

                        if args.split_by_size_32mb:
                            sub_dir_name = 'Small'
                            if f['file_size'] > 32 * 1024 * 1024:
                                sub_dir_name = "Large"
                            elif args.split_by_main_reg:
                                sub_dir_name = get_main_reg_subdir(info['regions'], rest_of_the_world)
                            target_dir_path = os.path.join(target_dir_path, sub_dir_name)
                        elif args.split_by_main_reg and info['license'] == CONST_LICENSED:
                            sub_dir_name = get_main_reg_subdir(info['regions'], rest_of_the_world)
                            target_dir_path = os.path.join(target_dir_path, sub_dir_name)

                        if args.split_by_abc:
                            sub_dir_name = '-'
                            for c in target_file_name:
                                if c.isalpha():
                                    sub_dir_name = c.upper()
                                    break
                                if c.isdigit():
                                    sub_dir_name = '0-9'
                                    break
                            target_dir_path = os.path.join(target_dir_path, sub_dir_name)

                    # Add the ROM to the export list
                    if not target_dir_path in files_to_export:
                        files_to_export[target_dir_path] = []

                    files_to_export[target_dir_path].append({
                        "package_path": f['package_path'],
                        "file_name": f['file_name'],
                        "target_file_name": target_file_name
                    })
        for target_dir_path, files_list in sorted(files_to_export.items()):
            sorted_files_list = sorted(files_list, key=lambda x: x['target_file_name'].lower())
            for f in sorted_files_list:
                export_file(f['package_path'], f['file_name'], target_dir_path, f['target_file_name'])
                exported_files += 1
        print()

        print(f"Files exported: {exported_files}\n")

if __name__ == "__main__":
    main()

